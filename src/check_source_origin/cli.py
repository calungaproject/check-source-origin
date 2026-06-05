from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from .diff import compare_trees
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
def diff(sdist: Path, repo: str, ref: str, use_json: bool, ignore: tuple[str, ...]) -> None:
    """Compare an sdist tarball against a VCS checkout."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        sdist_root = extract_sdist(sdist, tmp / "sdist")
        repo_dir = clone_repo(repo, ref, tmp / "repo")
        report = compare_trees(sdist_root, repo_dir, extra_ignore=list(ignore) or None)

    if use_json:
        click.echo(json.dumps(report.to_dict(), indent=2))
    else:
        _print_diff_report(report)

    if not report.passed:
        sys.exit(1)


@main.command()
@click.argument("name")
@click.argument("version")
@click.option("--json-output", "use_json", is_flag=True, help="Output as JSON")
@click.option("--sdist", "sdist_path", type=click.Path(exists=True, path_type=Path), default=None,
              help="Use a pre-downloaded sdist instead of fetching from PyPI")
def verify(name: str, version: str, use_json: bool, sdist_path: Path | None) -> None:
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
        _print_diff_report(result.diff_report)

    if not result.diff_report.passed:
        sys.exit(1)


def _print_diff_report(report: object) -> None:
    from .models import DiffReport
    assert isinstance(report, DiffReport)

    if report.passed:
        click.secho("PASS", fg="green", bold=True)
    else:
        click.secho("FAIL", fg="red", bold=True)

    if report.modified:
        click.echo(f"\nModified files ({len(report.modified)}):")
        for m in report.modified:
            click.echo(f"  {m.path}")

    if report.added:
        click.echo(f"\nFiles only in sdist ({len(report.added)}):")
        for a in report.added:
            click.echo(f"  + {a.path}")

    if report.removed:
        click.echo(f"\nFiles only in VCS ({len(report.removed)}):")
        for r in report.removed:
            click.echo(f"  - {r.path}")

    if report.generated:
        click.echo(f"\nGenerated/ignored files ({len(report.generated)}):")
        for g in report.generated:
            click.echo(f"  ~ {g.path}")
