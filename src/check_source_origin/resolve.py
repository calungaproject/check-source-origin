from __future__ import annotations

from typing import Any

from .depsdev import DepsDevClient
from .github import GitHubClient
from .models import ResolveResult
from .pypi import PyPIClient


class ResolveError(Exception):
    pass


def _repo_url_from_project_id(project_id: str) -> str:
    return f"https://{project_id}"


def _find_metadata_source_repo(
    related: list[dict[str, Any]],
) -> str | None:
    for p in related:
        if (
            p.get("relationType") == "SOURCE_REPO"
            and p.get("relationProvenance") == "UNVERIFIED_METADATA"
        ):
            return _repo_url_from_project_id(p["projectKey"]["id"])
    return None


def resolve_source(name: str, version: str) -> ResolveResult:
    depsdev = DepsDevClient()
    pypi = PyPIClient()

    depsdev_data = depsdev.get_version(name, version)
    related = DepsDevClient.extract_related_projects(depsdev_data)

    attestations = DepsDevClient.extract_attestations(depsdev_data)
    verified = [a for a in attestations if a.get("verified")]
    if verified:
        att = verified[0]
        repo_url = att["sourceRepository"]
        commit = att.get("commit")

        metadata_repo = _find_metadata_source_repo(related)
        if metadata_repo and metadata_repo != repo_url:
            repo_url = metadata_repo
            github = GitHubClient()
            commit = github.resolve_version_commit(repo_url, version)

        return ResolveResult(
            repo_url=repo_url,
            commit=commit,
            tag=None,
            resolution_method="attestation",
            verified=True,
        )

    source_repos = [
        p for p in related if p.get("relationType") == "SOURCE_REPO"
    ]
    if source_repos:
        project = source_repos[0]
        return ResolveResult(
            repo_url=_repo_url_from_project_id(project["projectKey"]["id"]),
            commit=None,
            tag=None,
            resolution_method="related_project",
            verified=False,
        )

    pypi_data = pypi.get_version_metadata(name, version)
    source_urls = PyPIClient.extract_source_urls(pypi_data)
    if source_urls:
        return ResolveResult(
            repo_url=source_urls[0],
            commit=None,
            tag=None,
            resolution_method="pypi_metadata",
            verified=False,
        )

    raise ResolveError(
        f"Could not resolve VCS source for {name}=={version}"
    )
