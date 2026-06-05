from __future__ import annotations

import re
from typing import Any

import httpx

_GITHUB_REPO_RE = re.compile(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$")

BASE_URL = "https://api.github.com"


class GitHubClient:
    def __init__(self) -> None:
        self._client = httpx.Client(base_url=BASE_URL, timeout=30)

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

    def resolve_version_commit(
        self, repo_url: str, version: str
    ) -> str | None:
        match = _GITHUB_REPO_RE.match(repo_url)
        if not match:
            return None
        owner, repo = match.group(1), match.group(2)
        for tag in (f"v{version}", version):
            commit = self.resolve_tag_commit(owner, repo, tag)
            if commit:
                return commit
        return None
