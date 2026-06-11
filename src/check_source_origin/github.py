from __future__ import annotations

import os
import re
from typing import Any, NamedTuple

import httpx

_GITHUB_REPO_RE = re.compile(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$")


class VersionCommitResult(NamedTuple):
    commit: str | None
    repo_url: str

BASE_URL = "https://api.github.com"


class GitHubClient:
    def __init__(self) -> None:
        headers: dict[str, str] = {}
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=BASE_URL, timeout=30, headers=headers
        )

    def resolve_tag_commit(
        self, owner: str, repo: str, tag: str
    ) -> str | None:
        resp = self._client.get(f"/repos/{owner}/{repo}/git/ref/tags/{tag}")
        if resp.status_code != 200:
            return None
        data: dict[str, Any] = resp.json()
        obj = data.get("object", {})
        if obj.get("type") == "commit":
            return obj.get("sha")  # type: ignore[no-any-return]
        if obj.get("type") == "tag":
            return self._dereference_tag(owner, repo, obj["sha"])
        return None

    def _dereference_tag(
        self, owner: str, repo: str, tag_sha: str
    ) -> str | None:
        resp = self._client.get(
            f"/repos/{owner}/{repo}/git/tags/{tag_sha}"
        )
        if resp.status_code != 200:
            return None
        data: dict[str, Any] = resp.json()
        obj = data.get("object", {})
        if obj.get("type") == "commit":
            return obj.get("sha")  # type: ignore[no-any-return]
        return None

    def _resolve_redirect(
        self, owner: str, repo: str
    ) -> tuple[str, str] | None:
        resp = self._client.get(
            f"/repos/{owner}/{repo}", follow_redirects=True
        )
        if resp.status_code != 200:
            return None
        if not resp.history:
            return None
        full_name = resp.json().get("full_name", "")
        if "/" not in full_name:
            return None
        new_owner, new_repo = full_name.split("/", 1)
        return new_owner, new_repo

    def resolve_version_commit(
        self, repo_url: str, version: str
    ) -> VersionCommitResult:
        match = _GITHUB_REPO_RE.match(repo_url)
        if not match:
            return VersionCommitResult(None, repo_url)
        owner, repo = match.group(1), match.group(2)
        for tag in (f"v{version}", version):
            commit = self.resolve_tag_commit(owner, repo, tag)
            if commit:
                return VersionCommitResult(commit, repo_url)

        redirected = self._resolve_redirect(owner, repo)
        if redirected:
            new_owner, new_repo = redirected
            new_url = f"https://github.com/{new_owner}/{new_repo}"
            for tag in (f"v{version}", version):
                commit = self.resolve_tag_commit(new_owner, new_repo, tag)
                if commit:
                    return VersionCommitResult(commit, new_url)
            return VersionCommitResult(None, new_url)

        return VersionCommitResult(None, repo_url)
