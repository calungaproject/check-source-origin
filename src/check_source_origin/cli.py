from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from .diff import compare_trees
from .generated import detect_generated_files
from .resolve import resolve_source
from .verify import clone_repo, extract_sdist, fetch_sdist, run_verify


@click.group()
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
        click.echo(f"Method:     {result.resolution_method}")
        click.echo(f"Verified:   {result.verified}")


@main.command()
@click.argument("name")
@click.argument("version")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
def download(name: str, version: str, output: Path | None) -> None:
    """Download the sdist for a package version from PyPI."""
    if output is None:
        output = Path(f"{name}-{version}.tar.gz")
    path = fetch_sdist(name, version, output)
    click.echo(f"Downloaded: {path}")


@main.command()
@click.argument("sdist", type=click.Path(exists=True, path_type=Path))
@click.option("--repo", required=True, help="VCS repository URL")
@click.option("--ref", required=True, help="Git ref (commit, tag, or branch)")
@click.option("--json-output", "use_json", is_flag=True, help="Output as JSON")
@click.option("--ignore", multiple=True, help="Extra glob patterns to treat as generated")
@click.option("--details", is_flag=True, help="Show excluded and generated files")
def diff(sdist: Path, repo: str, ref: str, use_json: bool, ignore: tuple[str, ...], details: bool) -> None:
    """Compare an sdist tarball against a VCS checkout."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        sdist_root = extract_sdist(sdist, tmp / "sdist")
        repo_dir = clone_repo(repo, ref, tmp / "repo")
        auto_generated = detect_generated_files(repo_dir)
        all_ignore = list(ignore) + auto_generated
        report = compare_trees(sdist_root, repo_dir, extra_ignore=all_ignore or None)

    if use_json:
        click.echo(json.dumps(report.to_dict(), indent=2))
    else:
        _print_diff_report(report, details=details)

    if not report.passed:
        sys.exit(1)


@main.command()
@click.argument("name")
@click.argument("version")
@click.option("--json-output", "use_json", is_flag=True, help="Output as JSON")
@click.option("--sdist", "sdist_path", type=click.Path(exists=True, path_type=Path), default=None,
              help="Use a pre-downloaded sdist instead of fetching from PyPI")
@click.option("--details", is_flag=True, help="Show excluded and generated files")
def verify(name: str, version: str, use_json: bool, sdist_path: Path | None, details: bool) -> None:
    """Full pipeline: resolve, download, and diff a package against its source."""
    result = run_verify(name, version, sdist_path=sdist_path)

    if use_json:
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        r = result.resolve_result
        click.echo(f"Repository: {r.repo_url}")
        click.echo(f"Commit:     {r.commit or '(unknown)'}")
        click.echo(f"Method:     {r.resolution_method}")
        click.echo(f"Verified:   {r.verified}")
        click.echo()
        _print_diff_report(result.diff_report, details=details)

    if not result.diff_report.passed:
        sys.exit(1)


def _print_diff_report(report: object, *, details: bool = False) -> None:
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
