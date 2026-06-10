from pathlib import Path

from check_source_origin.diff import compare_trees
from check_source_origin.generated import detect_generated_files


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestDetectGeneratedFiles:
    def test_no_pyproject_toml(self, tmp_path: Path) -> None:
        assert detect_generated_files(tmp_path) == []

    def test_invalid_toml(self, tmp_path: Path) -> None:
        _write(tmp_path / "pyproject.toml", "this is not valid toml [[[")
        assert detect_generated_files(tmp_path) == []

    def test_no_version_tool_config(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "pyproject.toml",
            '[project]\nname = "mypackage"\nversion = "1.0"\n',
        )
        assert detect_generated_files(tmp_path) == []

    def test_setuptools_scm_version_file(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "pyproject.toml",
            "[tool.setuptools_scm]\n"
            'version_file = "src/mypackage/_version.py"\n',
        )
        assert detect_generated_files(tmp_path) == ["src/mypackage/_version.py"]

    def test_setuptools_scm_write_to(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "pyproject.toml",
            "[tool.setuptools_scm]\n"
            'write_to = "mypackage/_version.py"\n',
        )
        assert detect_generated_files(tmp_path) == ["mypackage/_version.py"]

    def test_setuptools_scm_version_file_preferred_over_write_to(
        self, tmp_path: Path
    ) -> None:
        _write(
            tmp_path / "pyproject.toml",
            "[tool.setuptools_scm]\n"
            'version_file = "src/pkg/_version.py"\n'
            'write_to = "pkg/_version.py"\n',
        )
        result = detect_generated_files(tmp_path)
        assert "src/pkg/_version.py" in result
        assert "pkg/_version.py" in result

    def test_versioningit(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "pyproject.toml",
            "[tool.versioningit.write]\n"
            'file = "src/mypackage/_version.py"\n',
        )
        assert detect_generated_files(tmp_path) == ["src/mypackage/_version.py"]

    def test_hatch_vcs(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "pyproject.toml",
            "[tool.hatch.build.hooks.vcs]\n"
            'version-file = "src/mypackage/_version.py"\n',
        )
        assert detect_generated_files(tmp_path) == ["src/mypackage/_version.py"]

    def test_pdm_version_scm(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "pyproject.toml",
            "[tool.pdm.version]\n"
            'source = "scm"\n'
            'write_to = "mypackage/_version.py"\n',
        )
        assert detect_generated_files(tmp_path) == ["mypackage/_version.py"]

    def test_pdm_version_file_source_ignored(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "pyproject.toml",
            "[tool.pdm.version]\n"
            'source = "file"\n'
            'write_to = "mypackage/_version.py"\n',
        )
        assert detect_generated_files(tmp_path) == []

    def test_multiple_tools(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "pyproject.toml",
            "[tool.setuptools_scm]\n"
            'version_file = "pkg/_version.py"\n'
            "\n"
            "[tool.versioningit.write]\n"
            'file = "pkg/_ver2.py"\n',
        )
        result = detect_generated_files(tmp_path)
        assert "pkg/_version.py" in result
        assert "pkg/_ver2.py" in result

    def test_no_duplicates(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "pyproject.toml",
            "[tool.setuptools_scm]\n"
            'version_file = "pkg/_version.py"\n'
            'write_to = "pkg/_version.py"\n',
        )
        result = detect_generated_files(tmp_path)
        assert result == ["pkg/_version.py"]


class TestCompareTreesIntegration:
    def test_version_file_classified_as_generated(self, tmp_path: Path) -> None:
        sdist = tmp_path / "sdist"
        vcs = tmp_path / "vcs"
        _write(sdist / "pkg" / "main.py", "print('hi')")
        _write(sdist / "pkg" / "_version.py", '__version__ = "1.0"')
        _write(vcs / "pkg" / "main.py", "print('hi')")
        _write(
            vcs / "pyproject.toml",
            "[tool.setuptools_scm]\n"
            'version_file = "pkg/_version.py"\n',
        )

        auto = detect_generated_files(vcs)
        report = compare_trees(sdist, vcs, extra_ignore=auto)

        assert report.passed is True
        assert any("_version.py" in f.path for f in report.generated)

    def test_version_file_without_config_is_added(self, tmp_path: Path) -> None:
        sdist = tmp_path / "sdist"
        vcs = tmp_path / "vcs"
        _write(sdist / "pkg" / "main.py", "print('hi')")
        _write(sdist / "pkg" / "_version.py", '__version__ = "1.0"')
        _write(vcs / "pkg" / "main.py", "print('hi')")

        auto = detect_generated_files(vcs)
        report = compare_trees(sdist, vcs, extra_ignore=auto)

        assert report.passed is False
        assert any("_version.py" in f.path for f in report.added)
