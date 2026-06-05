import json
from pathlib import Path
from unittest.mock import patch

import httpx

from check_source_origin.resolve import resolve_source

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
        assert result.verified is True
        assert result.resolution_method == "attestation"
        assert "github.com" in result.repo_url
        assert result.commit is not None

    def test_unverified_metadata_fallback(self) -> None:
        with patch.object(
            httpx.Client,
            "get",
            side_effect=_mock_get({
                "deps.dev": "depsdev_requests_2.31.0.json",
                "pypi.org": "pypi_requests_2.31.0.json",
            }),
        ):
            result = resolve_source("requests", "2.31.0")
        assert result.verified is False
        assert result.resolution_method in ("related_project", "pypi_metadata")
        assert "github.com" in result.repo_url

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
