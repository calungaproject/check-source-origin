from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from .diff import compare_trees
from .generated import detect_generated_files
from .resolve import ResolveError, resolve_source
from .download import download_sdist
from .pypi import PyPIClient
from .verify import extract_sdist, fetch_repo, run_verify


class _CLI(click.Group):
    def invoke(self, ctx: click.Context) -> None:
        try:
            super().invoke(ctx)
        except ResolveError as e:
            click.echo(f"Error: {e}", err=True)
            ctx.exit(1)


@click.group(cls=_CLI)
def main() -> None:
    """Verify that a published Python sdist matches its claimed VCS source."""


@main.command()
@click.argument("name")
@click.argument("version")
@click.option("--json-output", "use_json", is_flag=True, help="Output as JSON")
def resolve(name: str, version: str, use_json: bool) -> None:
    """Resolve a package version to its VCS repository and commit."""
    result = resolve_source(name, version)
    if use_json:
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(f"Repository: {result.repo_url}")
        click.echo(f"Commit:     {result.commit or '(unknown)'}")
        click.echo(f"Tag:        {result.tag or '(unknown)'}")
        if result.subdir:
            click.echo(f"Subdir:     {result.subdir}")
        click.echo(f"Method:     {result.resolution_method}")


@main.command()
@click.argument("name")
@click.argument("version")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
def download(name: str, version: str, output: Path | None) -> None:
    """Download the sdist for a package version from PyPI."""
    pypi = PyPIClient()
    meta = pypi.get_version_metadata(name, version)
    sdist_info = PyPIClient.extract_sdist_info(meta)
    if sdist_info is None:
        raise click.ClickException(f"No sdist found for {name}=={version}")
    if output is None:
        output = Path(sdist_info.get("filename", f"{name}-{version}.tar.gz"))
    path = download_sdist(
        url=sdist_info["url"],
        expected_sha256=sdist_info["digests"]["sha256"],
        output=output,
    )
    click.echo(f"Downloaded: {path}")


@main.command()
@click.argument("sdist", type=click.Path(exists=True, path_type=Path))
@click.option("--repo", required=True, help="VCS repository URL")
@click.option("--ref", required=True, help="Git ref (commit, tag, or branch)")
@click.option("--json-output", "use_json", is_flag=True, help="Output as JSON")
@click.option("--ignore", multiple=True, help="Extra glob patterns to treat as generated")
@click.option("--details", is_flag=True, help="Show excluded and generated files")
@click.option("--show-diff", is_flag=True, help="Show actual file diffs for modified files")
@click.option("--subdir", default=None, help="Subdirectory within the repo containing the Python package (for mono-repos)")
def diff(sdist: Path, repo: str, ref: str, use_json: bool, ignore: tuple[str, ...], details: bool, show_diff: bool, subdir: str | None) -> None:
    """Compare an sdist tarball against a VCS checkout."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        sdist_root = extract_sdist(sdist, tmp / "sdist")
        repo_dir = fetch_repo(repo, ref, tmp / "repo")
        if subdir:
            repo_dir = repo_dir / subdir
        auto_generated = detect_generated_files(repo_dir)
        all_ignore = list(ignore) + auto_generated
        report = compare_trees(sdist_root, repo_dir, extra_ignore=all_ignore or None)

        if use_json:
            click.echo(json.dumps(report.to_dict(), indent=2))
        else:
            _print_diff_report(
                report, details=details, show_diff=show_diff,
                sdist_root=sdist_root, vcs_root=repo_dir,
            )

    if not report.passed:
        sys.exit(1)


@main.command()
@click.argument("name")
@click.argument("version")
@click.option("--json-output", "use_json", is_flag=True, help="Output as JSON")
@click.option("--sdist", "sdist_path", type=click.Path(exists=True, path_type=Path), default=None,
              help="Use a pre-downloaded sdist instead of fetching from PyPI")
@click.option("--details", is_flag=True, help="Show excluded and generated files")
@click.option("--show-diff", is_flag=True, help="Show actual file diffs for modified files")
def verify(name: str, version: str, use_json: bool, sdist_path: Path | None, details: bool, show_diff: bool) -> None:
    """Full pipeline: resolve, download, and diff a package against its source."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_verify(name, version, sdist_path=sdist_path, tmp_dir=Path(tmpdir))

        if use_json:
            click.echo(json.dumps(result.to_dict(), indent=2))
        elif result.diff_report is None:
            r = result.resolve_result
            click.echo(f"Repository: {r.repo_url}")
            click.echo(f"Commit:     {r.commit or '(unknown)'}")
            if r.subdir:
                click.echo(f"Subdir:     {r.subdir}")
            click.echo(f"Method:     {r.resolution_method}")
            click.echo()
            click.secho(
                f"SKIP — No sdist found for {name}=={version}."
                " Only a wheel is available on PyPI.",
                fg="yellow",
                bold=True,
            )
        else:
            r = result.resolve_result
            click.echo(f"Repository: {r.repo_url}")
            click.echo(f"Commit:     {r.commit or '(unknown)'}")
            if r.subdir:
                click.echo(f"Subdir:     {r.subdir}")
            click.echo(f"Method:     {r.resolution_method}")
            click.echo()
            _print_diff_report(
                result.diff_report, details=details, show_diff=show_diff,
                sdist_root=result.sdist_root, vcs_root=result.vcs_root,
            )

    if result.diff_report is None or not result.diff_report.passed:
        sys.exit(1)


def _show_file_diff(vcs_root: Path, sdist_root: Path, rel_path: str) -> None:
    import difflib

    try:
        vcs_lines = (vcs_root / rel_path).read_text().splitlines(keepends=True)
        sdist_lines = (sdist_root / rel_path).read_text().splitlines(keepends=True)
    except (UnicodeDecodeError, OSError):
        click.echo("    Binary or unreadable file")
        return

    diff = difflib.unified_diff(
        sdist_lines, vcs_lines,
        fromfile=f"sdist/{rel_path}",
        tofile=f"vcs/{rel_path}",
    )
    for line in diff:
        click.echo(f"    {line.rstrip(chr(10))}")


def _print_diff_report(
    report: object,
    *,
    details: bool = False,
    show_diff: bool = False,
    sdist_root: Path | None = None,
    vcs_root: Path | None = None,
) -> None:
    from .models import DiffReport
    assert isinstance(report, DiffReport)

    if report.passed:
        click.secho("PASS", fg="green", bold=True)
    else:
        click.secho("FAIL", fg="red", bold=True)

    if report.modified:
        click.secho(
            f"\nModified files ({len(report.modified)})"
            " — content differs between sdist and VCS:",
            fg="red",
        )
        for m in report.modified:
            click.secho(f"  {m.path}", fg="red")
            if show_diff and sdist_root is not None and vcs_root is not None:
                _show_file_diff(vcs_root, sdist_root, m.path)

    if report.added:
        click.secho(
            f"\nUnexpected files in sdist ({len(report.added)})"
            " — not found in VCS source:",
            fg="red",
        )
        for a in report.added:
            click.secho(f"  + {a.path}", fg="red")

    if details:
        if report.removed:
            click.secho(
                f"\nFiles excluded from sdist ({len(report.removed)})"
                " — present in VCS only:",
                dim=True,
            )
            for r in report.removed:
                click.secho(f"  - {r.path}", dim=True)

        if report.generated:
            click.secho(
                f"\nGenerated files ({len(report.generated)})"
                " — expected build artifacts:",
                dim=True,
            )
            for g in report.generated:
                click.secho(f"  ~ {g.path}", dim=True)
    else:
        hidden = []
        if report.removed:
            hidden.append(f"{len(report.removed)} excluded")
        if report.generated:
            hidden.append(f"{len(report.generated)} generated")
        if hidden:
            click.echo(f"\nUse --details to show {' and '.join(hidden)} files.")
