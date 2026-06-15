from __future__ import annotations

import os
import re
import tarfile
from pathlib import Path
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

    def _resolve_ref_object(
        self, owner: str, repo: str, obj: dict[str, Any]
    ) -> str | None:
        if obj.get("type") == "commit":
            return obj.get("sha")
        if obj.get("type") == "tag":
            return self._dereference_tag(owner, repo, obj["sha"])
        return None

    def resolve_tag_commit(
        self, owner: str, repo: str, tag: str
    ) -> str | None:
        resp = self._client.get(f"/repos/{owner}/{repo}/git/ref/tags/{tag}")
        if resp.status_code in (301, 404):
            return None
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return self._resolve_ref_object(owner, repo, data.get("object", {}))

    def _dereference_tag(
        self, owner: str, repo: str, tag_sha: str
    ) -> str | None:
        resp = self._client.get(
            f"/repos/{owner}/{repo}/git/tags/{tag_sha}"
        )
        if resp.status_code in (301, 404):
            return None
        resp.raise_for_status()
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
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        if not resp.history:
            return None
        full_name = resp.json().get("full_name", "")
        if "/" not in full_name:
            return None
        new_owner, new_repo = full_name.split("/", 1)
        return new_owner, new_repo

    def has_file(
        self, owner: str, repo: str, path: str, ref: str
    ) -> bool:
        resp = self._client.get(
            f"/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref},
        )
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True

    def download_tarball(
        self, owner: str, repo: str, ref: str, dest: Path
    ) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tarball = dest.parent / f"{repo}-{ref}.tar.gz"
        try:
            with self._client.stream(
                "GET",
                f"/repos/{owner}/{repo}/tarball/{ref}",
                follow_redirects=True,
            ) as resp:
                resp.raise_for_status()
                with open(tarball, "wb") as f:
                    for chunk in resp.iter_bytes():
                        f.write(chunk)
            with tarfile.open(tarball, "r:gz") as tar:
                tar.extractall(dest, filter="data")
            children = list(dest.iterdir())
            if len(children) == 1 and children[0].is_dir():
                children[0].rename(dest.parent / "__unwrap__")
                dest.rmdir()
                (dest.parent / "__unwrap__").rename(dest)
        finally:
            tarball.unlink(missing_ok=True)
        return dest

    def _matching_refs(
        self, owner: str, repo: str, prefix: str
    ) -> list[dict[str, Any]]:
        resp = self._client.get(
            f"/repos/{owner}/{repo}/git/matching-refs/tags/{prefix}"
        )
        if resp.status_code in (301, 404):
            return []
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    def _search_tags(
        self,
        owner: str,
        repo: str,
        name: str,
        version: str,
    ) -> str | None:
        commit = self._search_tags_for_version(owner, repo, name, version)
        if commit:
            return commit
        if version.endswith(".0"):
            return self._search_tags_for_version(
                owner, repo, name, version[:-2]
            )
        return None

    def _search_tags_for_version(
        self,
        owner: str,
        repo: str,
        name: str,
        version: str,
    ) -> str | None:
        # Version-prefixed: v{ver}, v{ver}-{suffix}
        refs = self._matching_refs(owner, repo, f"v{version}")
        for ref in refs:
            tag = ref["ref"].removeprefix("refs/tags/")
            if tag == f"v{version}":
                commit = self._resolve_ref_object(
                    owner, repo, ref.get("object", {})
                )
                if commit:
                    return commit
        parts = name.split("-")
        for i in range(len(parts) - 1, 0, -1):
            suffix = "-".join(parts[i:])
            candidate = f"v{version}-{suffix}"
            for ref in refs:
                tag = ref["ref"].removeprefix("refs/tags/")
                if tag == candidate:
                    commit = self._resolve_ref_object(
                        owner, repo, ref.get("object", {})
                    )
                    if commit:
                        return commit

        # Bare version: {ver}
        refs = self._matching_refs(owner, repo, version)
        for ref in refs:
            tag = ref["ref"].removeprefix("refs/tags/")
            if tag == version:
                commit = self._resolve_ref_object(
                    owner, repo, ref.get("object", {})
                )
                if commit:
                    return commit

        # release-{ver}
        refs = self._matching_refs(owner, repo, f"release-{version}")
        for ref in refs:
            tag = ref["ref"].removeprefix("refs/tags/")
            if tag == f"release-{version}":
                commit = self._resolve_ref_object(
                    owner, repo, ref.get("object", {})
                )
                if commit:
                    return commit

        # Name-prefixed with different separators
        for sep in ("-v", "_", "==", "-"):
            prefix = f"{name}{sep}{version}"
            refs = self._matching_refs(owner, repo, prefix)
            for ref in refs:
                tag = ref["ref"].removeprefix("refs/tags/")
                if tag == prefix:
                    commit = self._resolve_ref_object(
                        owner, repo, ref.get("object", {})
                    )
                    if commit:
                        return commit

        return None

    def resolve_version_commit(
        self, repo_url: str, version: str, name: str
    ) -> VersionCommitResult:
        match = _GITHUB_REPO_RE.match(repo_url)
        if not match:
            return VersionCommitResult(None, repo_url)
        owner, repo = match.group(1), match.group(2)

        commit = self._search_tags(owner, repo, name, version)
        if commit:
            return VersionCommitResult(commit, repo_url)

        redirected = self._resolve_redirect(owner, repo)
        if redirected:
            new_owner, new_repo = redirected
            new_url = f"https://github.com/{new_owner}/{new_repo}"
            commit = self._search_tags(new_owner, new_repo, name, version)
            if commit:
                return VersionCommitResult(commit, new_url)
            return VersionCommitResult(None, new_url)

        return VersionCommitResult(None, repo_url)
