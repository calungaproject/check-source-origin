from __future__ import annotations

import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dataclasses import replace

from .diff import compare_trees
from .generated import detect_generated_files
from .download import download_sdist
from .github import GitHubClient, _GITHUB_REPO_RE
from .known_repos import normalize
from .models import DiffReport, ResolveResult
from .pypi import PyPIClient
from .resolve import resolve_source


@dataclass(frozen=True)
class VerifyResult:
    resolve_result: ResolveResult
    diff_report: DiffReport
    sdist_root: Path | None = None
    vcs_root: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolve": self.resolve_result.to_dict(),
            "diff": self.diff_report.to_dict(),
        }


def find_package_subdir(repo_dir: Path, name: str) -> str | None:
    target = normalize(name)
    for pattern in ("setup.py", "pyproject.toml"):
        for path in repo_dir.rglob(pattern):
            parent = path.parent
            if parent == repo_dir:
                continue
            if normalize(parent.name) == target:
                return str(parent.relative_to(repo_dir))
    return None


def clone_repo(repo_url: str, ref: str, dest: Path) -> Path:
    subprocess.run(
        ["git", "clone", repo_url, str(dest)],
        check=True,
        capture_output=True,
    )
    try:
        subprocess.run(
            ["git", "-C", str(dest), "checkout", ref],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        subprocess.run(
            ["git", "-C", str(dest), "fetch", "origin", "tag", ref],
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


def fetch_repo(repo_url: str, ref: str, dest: Path) -> Path:
    match = _GITHUB_REPO_RE.match(repo_url)
    if match:
        owner, repo = match.group(1), match.group(2)
        gh = GitHubClient()
        if not gh.has_file(owner, repo, ".gitmodules", ref):
            return gh.download_tarball(owner, repo, ref, dest)
    return clone_repo(repo_url, ref, dest)


def extract_sdist(archive: Path, dest: Path) -> Path:
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(dest)
    else:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(dest, filter="data")
    children = list(dest.iterdir())
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return dest


def fetch_sdist(name: str, version: str, output_dir: Path) -> Path:
    pypi = PyPIClient()
    meta = pypi.get_version_metadata(name, version)
    sdist_info = PyPIClient.extract_sdist_info(meta)
    if sdist_info is None:
        raise RuntimeError(f"No sdist found for {name}=={version}")
    filename = sdist_info.get("filename", f"{name}-{version}.tar.gz")
    return download_sdist(
        url=sdist_info["url"],
        expected_sha256=sdist_info["digests"]["sha256"],
        output=output_dir / filename,
    )


def run_verify(
    name: str,
    version: str,
    work_dir: Path | None = None,
    sdist_path: Path | None = None,
    *,
    tmp_dir: Path | None = None,
) -> VerifyResult:
    resolved = resolve_source(name, version)
    ref = resolved.commit or resolved.tag or version

    if tmp_dir is not None:
        return _do_verify(resolved, name, version, ref, tmp_dir, sdist_path)

    with tempfile.TemporaryDirectory(dir=work_dir) as tmpdir:
        return _do_verify(resolved, name, version, ref, Path(tmpdir), sdist_path)


def _do_verify(
    resolved: ResolveResult,
    name: str,
    version: str,
    ref: str,
    tmp: Path,
    sdist_path: Path | None,
) -> VerifyResult:
    if sdist_path is None:
        sdist_path = fetch_sdist(name, version, tmp)

    sdist_root = extract_sdist(sdist_path, tmp / "sdist")
    repo_dir = fetch_repo(resolved.repo_url, ref, tmp / "repo")
    if not resolved.subdir:
        detected = find_package_subdir(repo_dir, name)
        if detected:
            resolved = replace(resolved, subdir=detected)
    vcs_root = repo_dir / resolved.subdir if resolved.subdir else repo_dir
    auto_generated = detect_generated_files(vcs_root)
    report = compare_trees(sdist_root, vcs_root, extra_ignore=auto_generated or None)

    return VerifyResult(
        resolve_result=resolved, diff_report=report,
        sdist_root=sdist_root, vcs_root=vcs_root,
    )
