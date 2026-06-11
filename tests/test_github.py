from unittest.mock import patch

from check_source_origin.github import GitHubClient


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
