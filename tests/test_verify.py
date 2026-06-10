import subprocess
import tarfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from check_source_origin.models import ResolveResult
from check_source_origin.verify import clone_repo, run_verify


def _make_sdist_tarball(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a .tar.gz with the given relative-path -> content mapping."""
    prefix = "pkg-1.0"
    tarball = tmp_path / "pkg-1.0.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        for rel_path, content in files.items():
            full = f"{prefix}/{rel_path}"
            data = content.encode()
            info = tarfile.TarInfo(name=full)
            info.size = len(data)
            tar.addfile(info, BytesIO(data))
    return tarball


def _make_git_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a fake git checkout directory."""
    repo = tmp_path / "repo"
    for rel_path, content in files.items():
        f = repo / rel_path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    return repo


_RESOLVE = ResolveResult(
    repo_url="https://github.com/test/pkg",
    commit="abc123",
    tag=None,
    resolution_method="attestation",
    verified=True,
)


def _init_local_repo(path: Path, files: dict[str, str]) -> str:
    """Create a local git repo with one commit and return its SHA."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )
    for rel_path, content in files.items():
        f = path / rel_path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    subprocess.run(
        ["git", "-C", str(path), "add", "."], check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        check=True, capture_output=True,
    )
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _init_submodule_repo(parent: Path, submodule_path: str, sub_files: dict[str, str]) -> None:
    """Add a git submodule to an existing repo."""
    sub_origin = parent.parent / "sub_origin"
    _init_local_repo(sub_origin, sub_files)
    subprocess.run(
        [
            "git", "-C", str(parent),
            "-c", "protocol.file.allow=always",
            "submodule", "add", str(sub_origin), submodule_path,
        ],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(parent), "commit", "-m", "add submodule"],
        check=True, capture_output=True,
    )


class TestCloneRepo:
    def test_clone_by_tag(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        files = {"hello.txt": "world"}
        _init_local_repo(origin, files)
        subprocess.run(
            ["git", "-C", str(origin), "tag", "v1.0"],
            check=True, capture_output=True,
        )
        dest = tmp_path / "clone"
        result = clone_repo(str(origin), "v1.0", dest)
        assert (result / "hello.txt").read_text() == "world"
        assert not (result / ".git").exists()

    def test_clone_by_commit_sha(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        files = {"hello.txt": "world"}
        sha = _init_local_repo(origin, files)
        dest = tmp_path / "clone"
        result = clone_repo(str(origin), sha, dest)
        assert (result / "hello.txt").read_text() == "world"
        assert not (result / ".git").exists()

    def test_clone_initializes_submodules(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        _init_local_repo(origin, {"hello.txt": "world"})
        _init_submodule_repo(origin, "libs/sub", {"lib.txt": "content"})
        subprocess.run(
            ["git", "-C", str(origin), "tag", "v2.0"],
            check=True, capture_output=True,
        )
        dest = tmp_path / "clone"
        result = clone_repo(str(origin), "v2.0", dest)
        assert (result / "libs/sub/lib.txt").read_text() == "content"
        assert not (result / ".git").exists()
        assert not (result / "libs/sub/.git").exists()
        assert (result / ".gitmodules").exists()


class TestRunVerify:
    def test_generated_version_file_auto_detected(self, tmp_path: Path) -> None:
        sdist = _make_sdist_tarball(
            tmp_path,
            {
                "src/main.py": "print('hello')",
                "src/pkg/_version.py": '__version__ = "1.0"',
            },
        )
        repo = _make_git_repo(
            tmp_path,
            {
                "src/main.py": "print('hello')",
                "pyproject.toml": (
                    "[tool.setuptools_scm]\n"
                    'version_file = "src/pkg/_version.py"\n'
                ),
            },
        )
        with (
            patch("check_source_origin.verify.resolve_source", return_value=_RESOLVE),
            patch("check_source_origin.verify.clone_repo", return_value=repo),
        ):
            result = run_verify("pkg", "1.0", tmp_path, sdist_path=sdist)

        assert result.diff_report.passed is True
        assert any(
            "_version.py" in f.path for f in result.diff_report.generated
        )

    def test_clean_match(self, tmp_path: Path) -> None:
        source_files = {"src/main.py": "print('hello')"}
        sdist = _make_sdist_tarball(tmp_path, source_files)
        repo = _make_git_repo(tmp_path, source_files)
        with (
            patch("check_source_origin.verify.resolve_source", return_value=_RESOLVE),
            patch("check_source_origin.verify.clone_repo", return_value=repo),
        ):
            result = run_verify("pkg", "1.0", tmp_path, sdist_path=sdist)

        assert result.diff_report.passed is True
        assert result.resolve_result.verified is True

    def test_tampered_file_detected(self, tmp_path: Path) -> None:
        sdist = _make_sdist_tarball(tmp_path, {"src/main.py": "evil()"})
        repo = _make_git_repo(tmp_path, {"src/main.py": "clean()"})
        with (
            patch("check_source_origin.verify.resolve_source", return_value=_RESOLVE),
            patch("check_source_origin.verify.clone_repo", return_value=repo),
        ):
            result = run_verify("pkg", "1.0", tmp_path, sdist_path=sdist)

        assert result.diff_report.passed is False
        assert len(result.diff_report.modified) == 1

    def test_extra_file_in_sdist_detected(self, tmp_path: Path) -> None:
        sdist = _make_sdist_tarball(
            tmp_path,
            {"src/main.py": "x", "src/backdoor.py": "import os"},
        )
        repo = _make_git_repo(tmp_path, {"src/main.py": "x"})
        with (
            patch("check_source_origin.verify.resolve_source", return_value=_RESOLVE),
            patch("check_source_origin.verify.clone_repo", return_value=repo),
        ):
            result = run_verify("pkg", "1.0", tmp_path, sdist_path=sdist)

        assert result.diff_report.passed is False
        assert any("backdoor" in f.path for f in result.diff_report.added)

    def test_to_dict_serializable(self, tmp_path: Path) -> None:
        source_files = {"main.py": "x"}
        sdist = _make_sdist_tarball(tmp_path, source_files)
        repo = _make_git_repo(tmp_path, source_files)
        with (
            patch("check_source_origin.verify.resolve_source", return_value=_RESOLVE),
            patch("check_source_origin.verify.clone_repo", return_value=repo),
        ):
            result = run_verify("pkg", "1.0", tmp_path, sdist_path=sdist)

        import json
        d = result.to_dict()
        json.dumps(d)
        assert d["resolve"]["verified"] is True
        assert d["diff"]["passed"] is True
