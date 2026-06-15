import subprocess
import tarfile
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from check_source_origin.models import ResolveResult
from check_source_origin.verify import clone_repo, extract_sdist, fetch_repo, find_package_subdir, run_verify


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


def _make_sdist_zip(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a .zip with the given relative-path -> content mapping."""
    prefix = "pkg-1.0"
    archive = tmp_path / "pkg-1.0.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for rel_path, content in files.items():
            zf.writestr(f"{prefix}/{rel_path}", content)
    return archive


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


class TestFindPackageSubdir:
    def test_finds_nested_setup_py(self, tmp_path: Path) -> None:
        repo = _make_git_repo(
            tmp_path,
            {
                "sdk/synapse/azure-synapse-artifacts/setup.py": "setup()",
                "sdk/storage/azure-storage-blob/setup.py": "setup()",
            },
        )
        assert find_package_subdir(repo, "azure-synapse-artifacts") == "sdk/synapse/azure-synapse-artifacts"

    def test_finds_pyproject_toml(self, tmp_path: Path) -> None:
        repo = _make_git_repo(
            tmp_path,
            {"sub/my-pkg/pyproject.toml": "[project]"},
        )
        assert find_package_subdir(repo, "my-pkg") == "sub/my-pkg"

    def test_returns_none_when_no_match(self, tmp_path: Path) -> None:
        repo = _make_git_repo(
            tmp_path,
            {"setup.py": "setup()", "other-pkg/setup.py": "setup()"},
        )
        assert find_package_subdir(repo, "nonexistent-pkg") is None

    def test_skips_root_setup_py(self, tmp_path: Path) -> None:
        repo = _make_git_repo(
            tmp_path,
            {"setup.py": "setup()"},
        )
        assert find_package_subdir(repo, "some-pkg") is None

    def test_normalizes_name(self, tmp_path: Path) -> None:
        repo = _make_git_repo(
            tmp_path,
            {"libs/my_pkg/setup.py": "setup()"},
        )
        assert find_package_subdir(repo, "my-pkg") == "libs/my_pkg"

    def test_finds_by_pyproject_name(self, tmp_path: Path) -> None:
        repo = _make_git_repo(
            tmp_path,
            {"libs/core/pyproject.toml": '[project]\nname = "langchain-core"\n'},
        )
        assert find_package_subdir(repo, "langchain-core") == "libs/core"


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

    def test_clone_fetches_tag_on_checkout_failure(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        files = {"hello.txt": "world"}
        _init_local_repo(origin, files)
        subprocess.run(
            ["git", "-C", str(origin), "tag", "v1.0"],
            check=True, capture_output=True,
        )
        dest = tmp_path / "clone"
        original_run = subprocess.run

        checkout_call_count = 0

        def patched_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            nonlocal checkout_call_count
            if cmd[0] == "git" and "checkout" in cmd:
                checkout_call_count += 1
                if checkout_call_count == 1:
                    raise subprocess.CalledProcessError(1, cmd)
            return original_run(cmd, **kwargs)

        with patch("check_source_origin.verify.subprocess.run", side_effect=patched_run):
            result = clone_repo(str(origin), "v1.0", dest)
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


class TestFetchRepo:
    def test_github_url_without_submodules_uses_tarball(self, tmp_path: Path) -> None:
        dest = tmp_path / "repo"
        expected = tmp_path / "result"
        with (
            patch("check_source_origin.verify.GitHubClient") as mock_cls,
            patch("check_source_origin.verify.clone_repo") as mock_clone,
        ):
            mock_gh = mock_cls.return_value
            mock_gh.has_file.return_value = False
            mock_gh.download_tarball.return_value = expected
            result = fetch_repo("https://github.com/owner/repo", "abc123", dest)

        mock_gh.has_file.assert_called_once_with("owner", "repo", ".gitmodules", "abc123")
        mock_gh.download_tarball.assert_called_once_with("owner", "repo", "abc123", dest)
        mock_clone.assert_not_called()
        assert result == expected

    def test_github_url_with_submodules_falls_back_to_clone(self, tmp_path: Path) -> None:
        dest = tmp_path / "repo"
        expected = tmp_path / "result"
        with (
            patch("check_source_origin.verify.GitHubClient") as mock_cls,
            patch("check_source_origin.verify.clone_repo", return_value=expected) as mock_clone,
        ):
            mock_gh = mock_cls.return_value
            mock_gh.has_file.return_value = True
            result = fetch_repo("https://github.com/owner/repo", "abc123", dest)

        mock_gh.download_tarball.assert_not_called()
        mock_clone.assert_called_once_with("https://github.com/owner/repo", "abc123", dest)
        assert result == expected

    def test_non_github_url_uses_clone(self, tmp_path: Path) -> None:
        dest = tmp_path / "repo"
        expected = tmp_path / "result"
        with (
            patch("check_source_origin.verify.GitHubClient") as mock_cls,
            patch("check_source_origin.verify.clone_repo", return_value=expected) as mock_clone,
        ):
            result = fetch_repo("https://gitlab.com/owner/repo", "abc123", dest)

        mock_cls.assert_not_called()
        mock_clone.assert_called_once_with("https://gitlab.com/owner/repo", "abc123", dest)
        assert result == expected


class TestExtractSdist:
    def test_extracts_tarball(self, tmp_path: Path) -> None:
        sdist = _make_sdist_tarball(tmp_path, {"hello.py": "print('hi')"})
        root = extract_sdist(sdist, tmp_path / "out")
        assert (root / "hello.py").read_text() == "print('hi')"

    def test_extracts_zip(self, tmp_path: Path) -> None:
        sdist = _make_sdist_zip(tmp_path, {"hello.py": "print('hi')"})
        root = extract_sdist(sdist, tmp_path / "out")
        assert (root / "hello.py").read_text() == "print('hi')"

    def test_zip_unwraps_single_dir(self, tmp_path: Path) -> None:
        sdist = _make_sdist_zip(tmp_path, {"a.py": "x", "b.py": "y"})
        root = extract_sdist(sdist, tmp_path / "out")
        assert root.name == "pkg-1.0"
        assert (root / "a.py").exists()


class TestRunVerifyWithZip:
    def test_clean_match(self, tmp_path: Path) -> None:
        source_files = {"src/main.py": "print('hello')"}
        sdist = _make_sdist_zip(tmp_path, source_files)
        repo = _make_git_repo(tmp_path, source_files)
        with (
            patch("check_source_origin.verify.resolve_source", return_value=_RESOLVE),
            patch("check_source_origin.verify.fetch_repo", return_value=repo),
        ):
            result = run_verify("pkg", "1.0", tmp_path, sdist_path=sdist)

        assert result.diff_report.passed is True

    def test_tampered_file_detected(self, tmp_path: Path) -> None:
        sdist = _make_sdist_zip(tmp_path, {"src/main.py": "evil()"})
        repo = _make_git_repo(tmp_path, {"src/main.py": "clean()"})
        with (
            patch("check_source_origin.verify.resolve_source", return_value=_RESOLVE),
            patch("check_source_origin.verify.fetch_repo", return_value=repo),
        ):
            result = run_verify("pkg", "1.0", tmp_path, sdist_path=sdist)

        assert result.diff_report.passed is False
        assert len(result.diff_report.modified) == 1


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
            patch("check_source_origin.verify.fetch_repo", return_value=repo),
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
            patch("check_source_origin.verify.fetch_repo", return_value=repo),
        ):
            result = run_verify("pkg", "1.0", tmp_path, sdist_path=sdist)

        assert result.diff_report.passed is True
        assert result.resolve_result.resolution_method == "attestation"

    def test_tampered_file_detected(self, tmp_path: Path) -> None:
        sdist = _make_sdist_tarball(tmp_path, {"src/main.py": "evil()"})
        repo = _make_git_repo(tmp_path, {"src/main.py": "clean()"})
        with (
            patch("check_source_origin.verify.resolve_source", return_value=_RESOLVE),
            patch("check_source_origin.verify.fetch_repo", return_value=repo),
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
            patch("check_source_origin.verify.fetch_repo", return_value=repo),
        ):
            result = run_verify("pkg", "1.0", tmp_path, sdist_path=sdist)

        assert result.diff_report.passed is False
        assert any("backdoor" in f.path for f in result.diff_report.added)

    def test_result_has_roots_with_tmp_dir(self, tmp_path: Path) -> None:
        source_files = {"src/main.py": "print('hello')"}
        sdist = _make_sdist_tarball(tmp_path, source_files)
        repo = _make_git_repo(tmp_path, source_files)
        work = tmp_path / "work"
        work.mkdir()
        with (
            patch("check_source_origin.verify.resolve_source", return_value=_RESOLVE),
            patch("check_source_origin.verify.fetch_repo", return_value=repo),
        ):
            result = run_verify("pkg", "1.0", sdist_path=sdist, tmp_dir=work)

        assert result.sdist_root is not None
        assert result.vcs_root is not None
        assert result.sdist_root.exists()
        assert result.vcs_root.exists()
        assert result.diff_report.passed is True

    def test_monorepo_subdir_narrows_comparison(self, tmp_path: Path) -> None:
        """When ResolveResult has a subdir, only that subtree is compared."""
        resolve_with_subdir = ResolveResult(
            repo_url="https://github.com/apache/avro",
            commit="abc123",
            tag=None,
            resolution_method="known_repos",
            subdir="lang/py",
        )
        sdist = _make_sdist_tarball(tmp_path, {"avro/__init__.py": "# avro"})
        repo = _make_git_repo(
            tmp_path,
            {
                "lang/py/avro/__init__.py": "# avro",
                "lang/java/pom.xml": "<project/>",
            },
        )
        with (
            patch("check_source_origin.verify.resolve_source", return_value=resolve_with_subdir),
            patch("check_source_origin.verify.fetch_repo", return_value=repo),
        ):
            result = run_verify("avro", "1.12.1", tmp_path, sdist_path=sdist)

        assert result.diff_report.passed is True

    def test_monorepo_subdir_auto_detected(self, tmp_path: Path) -> None:
        """When subdir is not set, auto-detect it from the cloned repo."""
        sdist = _make_sdist_tarball(
            tmp_path,
            {"azure/synapse/artifacts/__init__.py": "# artifacts"},
        )
        repo = _make_git_repo(
            tmp_path,
            {
                "sdk/synapse/azure-synapse-artifacts/setup.py": "setup()",
                "sdk/synapse/azure-synapse-artifacts/azure/synapse/artifacts/__init__.py": "# artifacts",
                "sdk/storage/azure-storage-blob/setup.py": "setup()",
            },
        )
        with (
            patch("check_source_origin.verify.resolve_source", return_value=_RESOLVE),
            patch("check_source_origin.verify.fetch_repo", return_value=repo),
        ):
            result = run_verify("azure-synapse-artifacts", "1.0", tmp_path, sdist_path=sdist)

        assert result.resolve_result.subdir == "sdk/synapse/azure-synapse-artifacts"
        assert result.diff_report.passed is True

    def test_to_dict_serializable(self, tmp_path: Path) -> None:
        source_files = {"main.py": "x"}
        sdist = _make_sdist_tarball(tmp_path, source_files)
        repo = _make_git_repo(tmp_path, source_files)
        with (
            patch("check_source_origin.verify.resolve_source", return_value=_RESOLVE),
            patch("check_source_origin.verify.fetch_repo", return_value=repo),
        ):
            result = run_verify("pkg", "1.0", tmp_path, sdist_path=sdist)

        import json
        d = result.to_dict()
        json.dumps(d)
        assert "verified" not in d["resolve"]
        assert d["diff"]["passed"] is True
