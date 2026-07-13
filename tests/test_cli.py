from pathlib import Path

from click.testing import CliRunner

from check_source_origin.cli import _print_diff_report, main
from check_source_origin.models import DiffReport, DiffResult, FileEntry
from check_source_origin.resolve import ResolveError


class TestPrintDiffReport:
    def _make_report(self) -> DiffReport:
        return DiffReport(
            added=[FileEntry(path="evil.py", digest="aaa")],
            removed=[
                FileEntry(path=".github/ci.yml", digest="bbb"),
                FileEntry(path="docs/index.rst", digest="ccc"),
            ],
            modified=[
                DiffResult(path="setup.py", sdist_digest="ddd", vcs_digest="eee")
            ],
            generated=[FileEntry(path="PKG-INFO", digest="fff")],
        )

    def test_default_shows_only_issues(self) -> None:
        report = self._make_report()
        output = _invoke_print(report, details=False)
        assert "FAIL" in output
        assert "Modified" in output
        assert "setup.py" in output
        assert "Unexpected" in output
        assert "evil.py" in output
        assert ".github/ci.yml" not in output
        assert "PKG-INFO" not in output

    def test_default_shows_hint(self) -> None:
        report = self._make_report()
        output = _invoke_print(report, details=False)
        assert "--details" in output
        assert "2 excluded" in output
        assert "1 generated" in output

    def test_no_hint_when_nothing_hidden(self) -> None:
        report = DiffReport(
            added=[FileEntry(path="evil.py", digest="aaa")],
            removed=[],
            modified=[],
            generated=[],
        )
        output = _invoke_print(report, details=False)
        assert "--details" not in output

    def test_details_shows_all_sections(self) -> None:
        report = self._make_report()
        output = _invoke_print(report, details=True)
        assert "FAIL" in output
        assert "setup.py" in output
        assert "evil.py" in output
        assert ".github/ci.yml" in output
        assert "PKG-INFO" in output

    def test_details_no_hint(self) -> None:
        report = self._make_report()
        output = _invoke_print(report, details=True)
        assert "--details" not in output

    def test_pass_no_issues(self) -> None:
        report = DiffReport(
            added=[],
            removed=[FileEntry(path=".github/ci.yml", digest="bbb")],
            modified=[],
            generated=[FileEntry(path="PKG-INFO", digest="fff")],
        )
        output = _invoke_print(report, details=False)
        assert "PASS" in output
        assert "Modified" not in output
        assert "Unexpected" not in output


def _invoke_print(
    report: DiffReport,
    details: bool,
    *,
    show_diff: bool = False,
    sdist_root: Path | None = None,
    vcs_root: Path | None = None,
) -> str:
    runner = CliRunner()
    import click

    @click.command()
    def _cmd() -> None:
        _print_diff_report(
            report,
            details=details,
            show_diff=show_diff,
            sdist_root=sdist_root,
            vcs_root=vcs_root,
        )

    result = runner.invoke(_cmd, catch_exceptions=False)
    return result.output


class TestShowDiff:
    def test_show_diff_displays_unified_diff(self, tmp_path: Path) -> None:
        sdist_root = tmp_path / "sdist"
        vcs_root = tmp_path / "vcs"
        sdist_root.mkdir()
        vcs_root.mkdir()
        (sdist_root / "setup.py").write_text("version = '2.0'\n")
        (vcs_root / "setup.py").write_text("version = '1.0'\n")

        report = DiffReport(
            modified=[DiffResult(path="setup.py", sdist_digest="ddd", vcs_digest="eee")],
        )
        output = _invoke_print(
            report, details=False, show_diff=True, sdist_root=sdist_root, vcs_root=vcs_root
        )
        assert "--- sdist/setup.py" in output
        assert "+++ vcs/setup.py" in output
        assert "-version = '2.0'" in output
        assert "+version = '1.0'" in output

    def test_show_diff_not_shown_by_default(self, tmp_path: Path) -> None:
        sdist_root = tmp_path / "sdist"
        vcs_root = tmp_path / "vcs"
        sdist_root.mkdir()
        vcs_root.mkdir()
        (sdist_root / "setup.py").write_text("version = '2.0'\n")
        (vcs_root / "setup.py").write_text("version = '1.0'\n")

        report = DiffReport(
            modified=[DiffResult(path="setup.py", sdist_digest="ddd", vcs_digest="eee")],
        )
        output = _invoke_print(report, details=False)
        assert "--- sdist/setup.py" not in output
        assert "+version = '1.0'" not in output

    def test_show_diff_binary_file(self, tmp_path: Path) -> None:
        sdist_root = tmp_path / "sdist"
        vcs_root = tmp_path / "vcs"
        sdist_root.mkdir()
        vcs_root.mkdir()
        (sdist_root / "image.bin").write_bytes(b"\x80\x81\x82")
        (vcs_root / "image.bin").write_bytes(b"\x90\x91\x92")

        report = DiffReport(
            modified=[DiffResult(path="image.bin", sdist_digest="ddd", vcs_digest="eee")],
        )
        output = _invoke_print(
            report, details=False, show_diff=True, sdist_root=sdist_root, vcs_root=vcs_root
        )
        assert "Binary" in output


class TestCLI:
    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Verify" in result.output

    def test_subcommands_listed(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert "resolve" in result.output
        assert "download" in result.output
        assert "diff" in result.output
        assert "verify" in result.output

    def test_resolve_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["resolve", "--help"])
        assert result.exit_code == 0
        assert "NAME" in result.output

    def test_verify_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["verify", "--help"])
        assert result.exit_code == 0
        assert "--show-diff" in result.output

    def test_diff_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["diff", "--help"])
        assert result.exit_code == 0
        assert "--repo" in result.output
        assert "--ref" in result.output
        assert "--show-diff" in result.output
        assert "--subdir" in result.output


class TestVerifyNoSdist:
    def test_no_sdist_shows_skip_and_exits_1(self) -> None:
        from unittest.mock import patch

        from check_source_origin.models import ResolveResult
        from check_source_origin.verify import VerifyResult

        resolve_result = ResolveResult(
            repo_url="https://github.com/test/pkg",
            commit="abc123",
            tag=None,
            resolution_method="related_project",
        )
        result = VerifyResult(resolve_result=resolve_result, reason="no_sdist")

        runner = CliRunner()
        with patch("check_source_origin.cli.run_verify", return_value=result):
            cli_result = runner.invoke(main, ["verify", "pkg", "1.0"])
        assert cli_result.exit_code == 1
        assert "SKIP" in cli_result.output
        assert "No sdist" in cli_result.output
        assert "Traceback" not in cli_result.output

    def test_no_sdist_json_output(self) -> None:
        import json
        from unittest.mock import patch

        from check_source_origin.models import ResolveResult
        from check_source_origin.verify import VerifyResult

        resolve_result = ResolveResult(
            repo_url="https://github.com/test/pkg",
            commit="abc123",
            tag=None,
            resolution_method="related_project",
        )
        result = VerifyResult(resolve_result=resolve_result, reason="no_sdist")

        runner = CliRunner()
        with patch("check_source_origin.cli.run_verify", return_value=result):
            cli_result = runner.invoke(main, ["verify", "--json-output", "pkg", "1.0"])
        assert cli_result.exit_code == 1
        data = json.loads(cli_result.output)
        assert data["diff"] is None
        assert data["reason"] == "no_sdist"


class TestErrorHandling:
    def test_resolve_error_shows_message_without_traceback(self) -> None:
        from unittest.mock import patch

        runner = CliRunner()
        with patch(
            "check_source_origin.cli.resolve_source",
            side_effect=ResolveError("could not resolve foo 1.0"),
        ):
            result = runner.invoke(main, ["resolve", "foo", "1.0"])
        assert result.exit_code == 1
        assert "Error: could not resolve foo 1.0" in result.output
        assert "Traceback" not in result.output

    def test_resolve_error_in_verify(self) -> None:
        from unittest.mock import patch

        runner = CliRunner()
        with patch(
            "check_source_origin.cli.run_verify",
            side_effect=ResolveError("no source found"),
        ):
            result = runner.invoke(main, ["verify", "foo", "1.0"])
        assert result.exit_code == 1
        assert "Error: no source found" in result.output
        assert "Traceback" not in result.output
