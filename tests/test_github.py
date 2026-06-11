from unittest.mock import patch

import httpx
import pytest

from check_source_origin.github import GitHubClient

_FAKE_REQ = httpx.Request("GET", "https://fake")


class TestGitHubClientAuth:
    def test_uses_gh_token(self) -> None:
        env = {"GH_TOKEN": "ghp_test123"}
        with patch.dict("os.environ", env, clear=True):
            client = GitHubClient()
        assert client._client.headers["Authorization"] == "Bearer ghp_test123"

    def test_falls_back_to_github_token(self) -> None:
        env = {"GITHUB_TOKEN": "ghp_fallback"}
        with patch.dict("os.environ", env, clear=True):
            client = GitHubClient()
        assert client._client.headers["Authorization"] == "Bearer ghp_fallback"

    def test_gh_token_takes_precedence(self) -> None:
        env = {"GH_TOKEN": "ghp_primary", "GITHUB_TOKEN": "ghp_secondary"}
        with patch.dict("os.environ", env, clear=True):
            client = GitHubClient()
        assert client._client.headers["Authorization"] == "Bearer ghp_primary"

    def test_no_auth_without_token(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        assert "Authorization" not in client._client.headers


class TestResolveTagCommit:
    def test_returns_none_on_404(self) -> None:
        resp = httpx.Response(404, json={}, request=_FAKE_REQ)
        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", return_value=resp):
            assert client.resolve_tag_commit("owner", "repo", "v1.0") is None

    def test_raises_on_403(self) -> None:
        resp = httpx.Response(403, json={"message": "rate limit"}, request=_FAKE_REQ)
        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", return_value=resp):
            with pytest.raises(httpx.HTTPStatusError):
                client.resolve_tag_commit("owner", "repo", "v1.0")

    def test_raises_on_500(self) -> None:
        resp = httpx.Response(500, json={}, request=_FAKE_REQ)
        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", return_value=resp):
            with pytest.raises(httpx.HTTPStatusError):
                client.resolve_tag_commit("owner", "repo", "v1.0")


class TestDereferenceTag:
    def test_returns_none_on_404(self) -> None:
        resp = httpx.Response(404, json={}, request=_FAKE_REQ)
        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", return_value=resp):
            assert client._dereference_tag("owner", "repo", "abc123") is None

    def test_raises_on_403(self) -> None:
        resp = httpx.Response(403, json={"message": "forbidden"}, request=_FAKE_REQ)
        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", return_value=resp):
            with pytest.raises(httpx.HTTPStatusError):
                client._dereference_tag("owner", "repo", "abc123")


class TestResolveRedirect:
    def test_returns_none_on_404(self) -> None:
        resp = httpx.Response(404, json={}, request=_FAKE_REQ)
        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", return_value=resp):
            assert client._resolve_redirect("owner", "repo") is None

    def test_raises_on_403(self) -> None:
        resp = httpx.Response(403, json={"message": "forbidden"}, request=_FAKE_REQ)
        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", return_value=resp):
            with pytest.raises(httpx.HTTPStatusError):
                client._resolve_redirect("owner", "repo")


class TestResolveVersionCommit:
    def test_finds_release_prefixed_tag(self) -> None:
        """Repos like apache/avro use 'release-X.Y.Z' tags."""
        not_found = httpx.Response(404, json={}, request=_FAKE_REQ)
        found = httpx.Response(
            200,
            json={"object": {"type": "commit", "sha": "abc123"}},
            request=_FAKE_REQ,
        )

        def side_effect(url: str, **kwargs: object) -> httpx.Response:
            if url.endswith("/tags/release-1.12.1"):
                return found
            return not_found

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", side_effect=side_effect):
            result = client.resolve_version_commit(
                "https://github.com/apache/avro", "1.12.1"
            )
        assert result.commit == "abc123"
        assert result.repo_url == "https://github.com/apache/avro"
