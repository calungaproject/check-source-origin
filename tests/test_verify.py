import tarfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from check_source_origin.models import ResolveResult
from check_source_origin.verify import run_verify


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


class TestRunVerify:
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
