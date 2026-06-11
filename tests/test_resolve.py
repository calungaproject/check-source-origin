import json
from pathlib import Path
from unittest.mock import patch

import httpx

from check_source_origin.resolve import ResolveError, resolve_source

FIXTURES = Path(__file__).parent / "fixtures"
_FAKE_REQ = httpx.Request("GET", "https://fake")


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _mock_get(fixtures: dict[str, str]):
    """Return a side_effect that dispatches by URL substring.

    httpx.Client with base_url passes relative paths to get(), so we check
    both the URL arg and common path fragments.
    """

    def side_effect(url: str, **kwargs):
        full = str(url)
        for key, fixture in fixtures.items():
            if key in full:
                data = _load_fixture(fixture)
                return httpx.Response(200, json=data, request=_FAKE_REQ)
        # Fallback: match on path patterns
        if "/systems/pypi/" in full:
            for key, fixture in fixtures.items():
                if "depsdev" in key or "deps.dev" in key:
                    data = _load_fixture(fixture)
                    return httpx.Response(200, json=data, request=_FAKE_REQ)
        if "/pypi/" in full:
            for key, fixture in fixtures.items():
                if "pypi" in key.lower() and "depsdev" not in key:
                    data = _load_fixture(fixture)
                    return httpx.Response(200, json=data, request=_FAKE_REQ)
        return httpx.Response(404, json={}, request=_FAKE_REQ)

    return side_effect


class TestResolveSource:
    def test_verified_attestation_path(self) -> None:
        with patch.object(
            httpx.Client,
            "get",
            side_effect=_mock_get({
                "deps.dev": "depsdev_flask_3.1.1.json",
                "pypi.org": "pypi_flask_3.1.1.json",
            }),
        ):
            result = resolve_source("flask", "3.1.1")
        assert result.resolution_method == "attestation"
        assert "github.com" in result.repo_url
        assert result.commit is not None

    def test_unverified_metadata_fallback(self) -> None:
        github_ref_resp = httpx.Response(
            200,
            json={
                "ref": "refs/tags/v2.31.0",
                "object": {"sha": "ffff", "type": "commit"},
            },
            request=_FAKE_REQ,
        )
        base = _mock_get({
            "deps.dev": "depsdev_requests_2.31.0.json",
            "pypi.org": "pypi_requests_2.31.0.json",
        })

        def mock_get(url: str, **kwargs):
            if "/git/ref/tags/" in str(url):
                return github_ref_resp
            return base(url, **kwargs)

        with patch.object(httpx.Client, "get", side_effect=mock_get):
            result = resolve_source("requests", "2.31.0")
        assert result.resolution_method in ("related_project", "pypi_metadata")
        assert "github.com" in result.repo_url
        assert result.commit is not None

    def test_attestation_cross_references_metadata_source_repo(self) -> None:
        """When attestation sourceRepository differs from UNVERIFIED_METADATA
        source repo, prefer the metadata repo (the actual source)."""
        github_ref_resp = httpx.Response(
            200,
            json={
                "ref": "refs/tags/v2.4.6",
                "object": {
                    "sha": "65daff092ee0f3d92f166630d32d6b9c81d99343",
                    "type": "tag",
                },
            },
            request=_FAKE_REQ,
        )
        github_tag_resp = httpx.Response(
            200,
            json={
                "object": {
                    "sha": "b832a09cf2a169c833dd2371e7c07aa00b293242",
                    "type": "commit",
                },
            },
            request=_FAKE_REQ,
        )

        def mock_get(url: str, **kwargs):
            full = str(url)
            if "/git/ref/tags/" in full:
                return github_ref_resp
            if "/git/tags/" in full:
                return github_tag_resp
            if "/systems/pypi/" in full:
                data = _load_fixture("depsdev_numpy_2.4.6.json")
                return httpx.Response(200, json=data, request=_FAKE_REQ)
            return httpx.Response(404, json={}, request=_FAKE_REQ)

        with patch.object(httpx.Client, "get", side_effect=mock_get):
            result = resolve_source("numpy", "2.4.6")
        assert result.repo_url == "https://github.com/numpy/numpy"
        assert result.commit == "b832a09cf2a169c833dd2371e7c07aa00b293242"
        assert result.resolution_method == "attestation"

    def test_related_project_resolves_commit(self) -> None:
        """When using related_project fallback, resolve the commit via GitHub."""
        github_ref_resp = httpx.Response(
            200,
            json={
                "ref": "refs/tags/v2.31.0",
                "object": {
                    "sha": "aaaa",
                    "type": "commit",
                },
            },
            request=_FAKE_REQ,
        )

        def mock_get(url: str, **kwargs):
            full = str(url)
            if "/git/ref/tags/" in full:
                return github_ref_resp
            if "/systems/pypi/" in full:
                data = _load_fixture("depsdev_requests_2.31.0.json")
                return httpx.Response(200, json=data, request=_FAKE_REQ)
            return httpx.Response(404, json={}, request=_FAKE_REQ)

        with patch.object(httpx.Client, "get", side_effect=mock_get):
            result = resolve_source("requests", "2.31.0")
        assert result.resolution_method == "related_project"
        assert result.commit == "aaaa"

    def test_pypi_metadata_resolves_commit(self) -> None:
        """When using pypi_metadata fallback, resolve the commit via GitHub."""
        empty_depsdev = {
            "versionKey": {"system": "PYPI", "name": "x", "version": "0"},
            "attestations": [],
            "relatedProjects": [],
            "links": [],
        }
        github_ref_resp = httpx.Response(
            200,
            json={
                "ref": "refs/tags/v1.0.0",
                "object": {
                    "sha": "bbbb",
                    "type": "commit",
                },
            },
            request=_FAKE_REQ,
        )
        pypi_data = {
            "info": {
                "name": "somepkg",
                "project_urls": {
                    "Source": "https://github.com/owner/somepkg",
                },
                "home_page": None,
            },
            "urls": [],
        }

        def mock_get(url: str, **kwargs):
            full = str(url)
            if "/git/ref/tags/" in full:
                return github_ref_resp
            if "/systems/pypi/" in full:
                return httpx.Response(200, json=empty_depsdev, request=_FAKE_REQ)
            if "/pypi/" in full:
                return httpx.Response(200, json=pypi_data, request=_FAKE_REQ)
            return httpx.Response(404, json={}, request=_FAKE_REQ)

        with patch.object(httpx.Client, "get", side_effect=mock_get):
            result = resolve_source("somepkg", "1.0.0")
        assert result.resolution_method == "pypi_metadata"
        assert result.commit == "bbbb"

    def test_known_repos_fallback(self) -> None:
        """When all methods fail but the package is in KNOWN_REPOS, use it."""
        empty_depsdev = {
            "versionKey": {"system": "PYPI", "name": "adlfs", "version": "1.0"},
            "attestations": [],
            "relatedProjects": [],
            "links": [],
        }
        empty_pypi = {
            "info": {"name": "adlfs", "project_urls": None, "home_page": None},
            "urls": [],
        }
        github_ref_resp = httpx.Response(
            200,
            json={
                "ref": "refs/tags/v1.0",
                "object": {"sha": "cccc", "type": "commit"},
            },
            request=_FAKE_REQ,
        )

        def mock_get(url: str, **kwargs):
            full = str(url)
            if "/git/ref/tags/" in full:
                return github_ref_resp
            if "/systems/pypi/" in full:
                return httpx.Response(200, json=empty_depsdev, request=_FAKE_REQ)
            if "/pypi/" in full:
                return httpx.Response(200, json=empty_pypi, request=_FAKE_REQ)
            return httpx.Response(404, json={}, request=_FAKE_REQ)

        with patch.object(httpx.Client, "get", side_effect=mock_get):
            result = resolve_source("adlfs", "1.0")
        assert result.resolution_method == "known_repos"
        assert result.repo_url == "https://github.com/fsspec/adlfs"
        assert result.commit == "cccc"
        assert result.subdir is None

    def test_known_repos_with_subdir(self) -> None:
        """Mono-repo packages carry subdir through to ResolveResult."""
        empty_depsdev = {
            "versionKey": {"system": "PYPI", "name": "avro", "version": "1.12.1"},
            "attestations": [],
            "relatedProjects": [],
            "links": [],
        }
        empty_pypi = {
            "info": {"name": "avro", "project_urls": None, "home_page": None},
            "urls": [],
        }
        github_ref_resp = httpx.Response(
            200,
            json={
                "ref": "refs/tags/release-1.12.1",
                "object": {"sha": "eeee", "type": "commit"},
            },
            request=_FAKE_REQ,
        )

        def mock_get(url: str, **kwargs):
            full = str(url)
            if "/git/ref/tags/" in full:
                if "release-1.12.1" in full:
                    return github_ref_resp
                return httpx.Response(404, json={}, request=_FAKE_REQ)
            if "/systems/pypi/" in full:
                return httpx.Response(200, json=empty_depsdev, request=_FAKE_REQ)
            if "/pypi/" in full:
                return httpx.Response(200, json=empty_pypi, request=_FAKE_REQ)
            return httpx.Response(404, json={}, request=_FAKE_REQ)

        with patch.object(httpx.Client, "get", side_effect=mock_get):
            result = resolve_source("avro", "1.12.1")
        assert result.resolution_method == "known_repos"
        assert result.repo_url == "https://github.com/apache/avro"
        assert result.subdir == "lang/py"

    def test_known_repos_skipped_when_not_in_db(self) -> None:
        """Unknown packages still raise ResolveError."""
        empty_depsdev = {
            "versionKey": {"system": "PYPI", "name": "x", "version": "0"},
            "attestations": [],
            "relatedProjects": [],
            "links": [],
        }
        empty_pypi = {
            "info": {"name": "x", "project_urls": None, "home_page": None},
            "urls": [],
        }

        def mock_get(url: str, **kwargs):
            full = str(url)
            if "/systems/pypi/" in full:
                return httpx.Response(200, json=empty_depsdev, request=_FAKE_REQ)
            if "/pypi/" in full:
                return httpx.Response(200, json=empty_pypi, request=_FAKE_REQ)
            return httpx.Response(404, json={}, request=_FAKE_REQ)

        with patch.object(httpx.Client, "get", side_effect=mock_get):
            try:
                resolve_source("unknown-pkg-xyz", "0.0.1")
                assert False, "Should have raised"
            except Exception as e:
                assert "could not resolve" in str(e).lower()

    def test_follows_repo_redirect(self) -> None:
        """When a repo was renamed, follow the GitHub redirect to find the tag."""
        redirect_resp = httpx.Response(
            301,
            headers={
                "location": "https://api.github.com/repositories/12345"
            },
            request=_FAKE_REQ,
        )
        repo_resp = httpx.Response(
            200,
            json={"full_name": "new-owner/pkg"},
            request=_FAKE_REQ,
            history=[redirect_resp],
        )
        github_ref_resp = httpx.Response(
            200,
            json={
                "ref": "refs/tags/v1.0.0",
                "object": {"sha": "dddd", "type": "commit"},
            },
            request=_FAKE_REQ,
        )
        depsdev_data = {
            "versionKey": {
                "system": "PYPI",
                "name": "pkg",
                "version": "1.0.0",
            },
            "attestations": [],
            "relatedProjects": [
                {
                    "relationType": "SOURCE_REPO",
                    "projectKey": {"id": "github.com/old-owner/pkg"},
                }
            ],
            "links": [],
        }

        def mock_get(url: str, **kwargs):
            full = str(url)
            if "/repos/old-owner/pkg/git/ref/tags/" in full:
                return httpx.Response(404, json={}, request=_FAKE_REQ)
            if "/repos/new-owner/pkg/git/ref/tags/" in full:
                return github_ref_resp
            if "/repos/old-owner/pkg" in full and "/git/" not in full:
                return repo_resp
            if "/systems/pypi/" in full:
                return httpx.Response(
                    200, json=depsdev_data, request=_FAKE_REQ
                )
            return httpx.Response(404, json={}, request=_FAKE_REQ)

        with patch.object(httpx.Client, "get", side_effect=mock_get):
            result = resolve_source("pkg", "1.0.0")
        assert result.commit == "dddd"
        assert result.repo_url == "https://github.com/new-owner/pkg"
        assert result.resolution_method == "related_project"

    def test_raises_when_commit_not_resolved(self) -> None:
        """Should raise when repo is found but no matching tag exists."""
        depsdev_data = {
            "versionKey": {"system": "PYPI", "name": "pkg", "version": "1.0.0"},
            "attestations": [],
            "relatedProjects": [
                {
                    "relationType": "SOURCE_REPO",
                    "projectKey": {"id": "github.com/owner/pkg"},
                }
            ],
            "links": [],
        }

        def mock_get(url: str, **kwargs):
            full = str(url)
            if "/systems/pypi/" in full:
                return httpx.Response(200, json=depsdev_data, request=_FAKE_REQ)
            return httpx.Response(404, json={}, request=_FAKE_REQ)

        with patch.object(httpx.Client, "get", side_effect=mock_get):
            try:
                resolve_source("pkg", "1.0.0")
                assert False, "Should have raised"
            except ResolveError as e:
                assert "commit" in str(e).lower()

    def test_raises_when_nothing_found(self) -> None:
        empty_depsdev = {
            "versionKey": {"system": "PYPI", "name": "x", "version": "0"},
            "attestations": [],
            "relatedProjects": [],
            "links": [],
        }
        empty_pypi = {
            "info": {"name": "x", "project_urls": None, "home_page": None},
            "urls": [],
        }

        def mock_get(url: str, **kwargs):
            if "deps.dev" in str(url):
                return httpx.Response(200, json=empty_depsdev, request=_FAKE_REQ)
            return httpx.Response(200, json=empty_pypi, request=_FAKE_REQ)

        with patch.object(httpx.Client, "get", side_effect=mock_get):
            try:
                resolve_source("x", "0")
                assert False, "Should have raised"
            except Exception as e:
                assert "could not resolve" in str(e).lower()
