from __future__ import annotations

import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .diff import compare_trees
from .download import download_sdist
from .models import DiffReport, ResolveResult
from .pypi import PyPIClient
from .resolve import resolve_source


@dataclass(frozen=True)
class VerifyResult:
    resolve_result: ResolveResult
    diff_report: DiffReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolve": self.resolve_result.to_dict(),
            "diff": self.diff_report.to_dict(),
        }


def clone_repo(repo_url: str, ref: str, dest: Path) -> Path:
    subprocess.run(
        ["git", "clone", repo_url, str(dest)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(dest), "checkout", ref],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git", "-C", str(dest),
            "-c", "protocol.file.allow=always",
            "submodule", "update", "--init", "--recursive",
        ],
        check=True,
        capture_output=True,
    )
    import shutil
    git_dir = dest / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)
    for git_path in dest.rglob(".git"):
        if git_path.is_file():
            git_path.unlink()
        elif git_path.is_dir():
            shutil.rmtree(git_path)
    return dest


def extract_sdist(tarball: Path, dest: Path) -> Path:
    with tarfile.open(tarball, "r:gz") as tar:
        tar.extractall(dest, filter="data")
    children = list(dest.iterdir())
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return dest


def fetch_sdist(name: str, version: str, output: Path) -> Path:
    pypi = PyPIClient()
    meta = pypi.get_version_metadata(name, version)
    sdist_info = PyPIClient.extract_sdist_info(meta)
    if sdist_info is None:
        raise RuntimeError(f"No sdist found for {name}=={version}")
    return download_sdist(
        url=sdist_info["url"],
        expected_sha256=sdist_info["digests"]["sha256"],
        output=output,
    )


def run_verify(
    name: str,
    version: str,
    work_dir: Path | None = None,
    sdist_path: Path | None = None,
) -> VerifyResult:
    resolved = resolve_source(name, version)
    ref = resolved.commit or resolved.tag or version

    with tempfile.TemporaryDirectory(dir=work_dir) as tmpdir:
        tmp = Path(tmpdir)

        if sdist_path is None:
            sdist_path = fetch_sdist(name, version, tmp / f"{name}-{version}.tar.gz")

        sdist_root = extract_sdist(sdist_path, tmp / "sdist")
        repo_dir = clone_repo(resolved.repo_url, ref, tmp / "repo")
        report = compare_trees(sdist_root, repo_dir)

    return VerifyResult(resolve_result=resolved, diff_report=report)
