import hashlib
from pathlib import Path

from check_source_origin.diff import (
    compare_trees,
    hash_file,
    is_generated,
)


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


class TestHashFile:
    def test_returns_sha256(self, tmp_path: Path) -> None:
        f = tmp_path / "hello.txt"
        f.write_text("hello")
        assert hash_file(f) == _sha256("hello")

    def test_normalizes_crlf_to_lf(self, tmp_path: Path) -> None:
        f = tmp_path / "crlf.txt"
        f.write_bytes(b"line1\r\nline2\r\n")
        lf = tmp_path / "lf.txt"
        lf.write_bytes(b"line1\nline2\n")
        assert hash_file(f) == hash_file(lf)


class TestIsGenerated:
    def test_pkg_info(self) -> None:
        assert is_generated("PKG-INFO") is True

    def test_egg_info_dir(self) -> None:
        assert is_generated("mypackage.egg-info/SOURCES.txt") is True

    def test_dist_info(self) -> None:
        assert is_generated("mypackage-1.0.dist-info/METADATA") is True

    def test_regular_source(self) -> None:
        assert is_generated("mypackage/core.py") is False

    def test_setup_cfg(self) -> None:
        assert is_generated("setup.cfg") is True

    def test_gitignore(self) -> None:
        assert is_generated(".gitignore") is True

    def test_nested_source(self) -> None:
        assert is_generated("src/mypackage/utils.py") is False


class TestCompareTrees:
    def test_identical_trees(self, tmp_path: Path) -> None:
        sdist = tmp_path / "sdist"
        vcs = tmp_path / "vcs"
        _write(sdist / "pkg" / "main.py", "print('hi')")
        _write(vcs / "pkg" / "main.py", "print('hi')")
        report = compare_trees(sdist, vcs)
        assert report.passed is True
        assert report.added == []
        assert report.removed == []
        assert report.modified == []

    def test_added_file_in_sdist(self, tmp_path: Path) -> None:
        sdist = tmp_path / "sdist"
        vcs = tmp_path / "vcs"
        _write(sdist / "pkg" / "main.py", "print('hi')")
        _write(sdist / "pkg" / "evil.py", "import os; os.system('rm -rf /')")
        _write(vcs / "pkg" / "main.py", "print('hi')")
        report = compare_trees(sdist, vcs)
        assert report.passed is False
        assert len(report.added) == 1
        assert report.added[0].path == "pkg/evil.py"

    def test_modified_file(self, tmp_path: Path) -> None:
        sdist = tmp_path / "sdist"
        vcs = tmp_path / "vcs"
        _write(sdist / "main.py", "print('tampered')")
        _write(vcs / "main.py", "print('original')")
        report = compare_trees(sdist, vcs)
        assert report.passed is False
        assert len(report.modified) == 1
        assert report.modified[0].path == "main.py"

    def test_removed_file_is_informational(self, tmp_path: Path) -> None:
        sdist = tmp_path / "sdist"
        vcs = tmp_path / "vcs"
        _write(sdist / "main.py", "x")
        _write(vcs / "main.py", "x")
        _write(vcs / ".github" / "ci.yml", "workflow")
        report = compare_trees(sdist, vcs)
        assert report.passed is True
        assert len(report.removed) == 1
        assert report.removed[0].path == ".github/ci.yml"

    def test_generated_files_classified(self, tmp_path: Path) -> None:
        sdist = tmp_path / "sdist"
        vcs = tmp_path / "vcs"
        _write(sdist / "main.py", "x")
        _write(sdist / "PKG-INFO", "Metadata-Version: 2.1")
        _write(sdist / "mypackage.egg-info" / "SOURCES.txt", "main.py")
        _write(vcs / "main.py", "x")
        report = compare_trees(sdist, vcs)
        assert report.passed is True
        assert len(report.generated) == 2
        gen_paths = {f.path for f in report.generated}
        assert "PKG-INFO" in gen_paths
        assert "mypackage.egg-info/SOURCES.txt" in gen_paths

    def test_modified_generated_file_classified(self, tmp_path: Path) -> None:
        sdist = tmp_path / "sdist"
        vcs = tmp_path / "vcs"
        _write(sdist / "main.py", "x")
        _write(sdist / "setup.cfg", "[metadata]\nversion = 1.0")
        _write(vcs / "main.py", "x")
        _write(vcs / "setup.cfg", "[metadata]")
        report = compare_trees(sdist, vcs)
        assert report.passed is True
        assert report.modified == []
        assert len(report.generated) == 1
        assert report.generated[0].path == "setup.cfg"

    def test_pyproject_version_only_change_is_generated(self, tmp_path: Path) -> None:
        sdist = tmp_path / "sdist"
        vcs = tmp_path / "vcs"
        _write(sdist / "main.py", "x")
        _write(
            sdist / "pyproject.toml",
            '[project]\nname = "pkg"\nversion = "1.2.3"\n',
        )
        _write(vcs / "main.py", "x")
        _write(
            vcs / "pyproject.toml",
            '[project]\nname = "pkg"\nversion = "0.0.0"\n',
        )
        report = compare_trees(sdist, vcs)
        assert report.passed is True
        assert report.modified == []
        assert any(g.path == "pyproject.toml" for g in report.generated)

    def test_pyproject_version_and_other_change_stays_modified(self, tmp_path: Path) -> None:
        sdist = tmp_path / "sdist"
        vcs = tmp_path / "vcs"
        _write(sdist / "main.py", "x")
        _write(
            sdist / "pyproject.toml",
            '[project]\nname = "evil"\nversion = "1.2.3"\n',
        )
        _write(vcs / "main.py", "x")
        _write(
            vcs / "pyproject.toml",
            '[project]\nname = "pkg"\nversion = "0.0.0"\n',
        )
        report = compare_trees(sdist, vcs)
        assert report.passed is False
        assert any(m.path == "pyproject.toml" for m in report.modified)

    def test_pyproject_no_version_in_either_stays_modified(self, tmp_path: Path) -> None:
        sdist = tmp_path / "sdist"
        vcs = tmp_path / "vcs"
        _write(sdist / "main.py", "x")
        _write(sdist / "pyproject.toml", '[project]\nname = "evil"\n')
        _write(vcs / "main.py", "x")
        _write(vcs / "pyproject.toml", '[project]\nname = "pkg"\n')
        report = compare_trees(sdist, vcs)
        assert report.passed is False
        assert any(m.path == "pyproject.toml" for m in report.modified)

    def test_pyproject_invalid_toml_stays_modified(self, tmp_path: Path) -> None:
        sdist = tmp_path / "sdist"
        vcs = tmp_path / "vcs"
        _write(sdist / "main.py", "x")
        _write(sdist / "pyproject.toml", "not valid toml [[[")
        _write(vcs / "main.py", "x")
        _write(vcs / "pyproject.toml", '[project]\nname = "pkg"\n')
        report = compare_trees(sdist, vcs)
        assert report.passed is False
        assert any(m.path == "pyproject.toml" for m in report.modified)

    def test_crlf_vs_lf_not_modified(self, tmp_path: Path) -> None:
        sdist = tmp_path / "sdist"
        vcs = tmp_path / "vcs"
        sdist.mkdir()
        vcs.mkdir()
        (sdist / "main.py").write_bytes(b"print('hi')\r\n")
        (vcs / "main.py").write_bytes(b"print('hi')\n")
        report = compare_trees(sdist, vcs)
        assert report.passed is True
        assert report.modified == []

    def test_extra_ignore_patterns(self, tmp_path: Path) -> None:
        sdist = tmp_path / "sdist"
        vcs = tmp_path / "vcs"
        _write(sdist / "main.py", "x")
        _write(sdist / "vendor" / "lib.py", "vendored")
        _write(vcs / "main.py", "x")
        report = compare_trees(sdist, vcs, extra_ignore=["vendor/*"])
        assert report.passed is True
        assert len(report.generated) == 1
