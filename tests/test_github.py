import tarfile
from io import BytesIO
from pathlib import Path
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
                "https://github.com/apache/avro", "1.12.1", "avro"
            )
        assert result.commit == "abc123"
        assert result.repo_url == "https://github.com/apache/avro"

    def test_finds_name_prefixed_tag(self) -> None:
        """Monorepos like azure-sdk-for-python use '{name}_{version}' tags."""
        not_found = httpx.Response(404, json={}, request=_FAKE_REQ)
        found = httpx.Response(
            200,
            json={"object": {"type": "commit", "sha": "def456"}},
            request=_FAKE_REQ,
        )

        def side_effect(url: str, **kwargs: object) -> httpx.Response:
            if url.endswith("/tags/azure-synapse-artifacts_0.22.0"):
                return found
            return not_found

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", side_effect=side_effect):
            result = client.resolve_version_commit(
                "https://github.com/Azure/azure-sdk-for-python",
                "0.22.0",
                name="azure-synapse-artifacts",
            )
        assert result.commit == "def456"
        assert result.repo_url == "https://github.com/Azure/azure-sdk-for-python"

    def test_name_prefixed_tag_tried_after_generic(self) -> None:
        """The name-prefixed tag is tried after v{version}, {version}, release-{version}."""
        not_found = httpx.Response(404, json={}, request=_FAKE_REQ)
        tried: list[str] = []

        def side_effect(url: str, **kwargs: object) -> httpx.Response:
            if "/tags/" in str(url):
                tried.append(str(url).rsplit("/tags/", 1)[1])
            return not_found

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", side_effect=side_effect):
            result = client.resolve_version_commit(
                "https://github.com/owner/repo", "1.0.0", "mypkg"
            )
        assert result.commit is None
        assert tried == ["v1.0.0", "1.0.0", "release-1.0.0", "mypkg_1.0.0"]

    def test_finds_version_suffixed_tag(self) -> None:
        """Monorepos like azure-storage-python use 'v{version}-{suffix}' tags."""
        not_found = httpx.Response(404, json={}, request=_FAKE_REQ)
        found = httpx.Response(
            200,
            json={"object": {"type": "commit", "sha": "abc123"}},
            request=_FAKE_REQ,
        )

        def side_effect(url: str, **kwargs: object) -> httpx.Response:
            if url.endswith("/tags/v2.1.0-common"):
                return found
            return not_found

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", side_effect=side_effect):
            result = client.resolve_version_commit(
                "https://github.com/Azure/azure-storage-python",
                "2.1.0",
                name="azure-storage-common",
            )
        assert result.commit == "abc123"
        assert result.repo_url == "https://github.com/Azure/azure-storage-python"

    def test_version_suffixed_tags_try_shortest_suffix_first(self) -> None:
        """Suffixed tags are tried shortest-first after the base patterns."""
        not_found = httpx.Response(404, json={}, request=_FAKE_REQ)
        tried: list[str] = []

        def side_effect(url: str, **kwargs: object) -> httpx.Response:
            if "/tags/" in str(url):
                tried.append(str(url).rsplit("/tags/", 1)[1])
            return not_found

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", side_effect=side_effect):
            client.resolve_version_commit(
                "https://github.com/owner/repo", "1.0.0", "a-b-c"
            )
        assert tried == [
            "v1.0.0", "1.0.0", "release-1.0.0", "a-b-c_1.0.0",
            "v1.0.0-c", "v1.0.0-b-c",
        ]


class TestHasFile:
    def test_returns_true_on_200(self) -> None:
        resp = httpx.Response(200, json={"type": "file"}, request=_FAKE_REQ)
        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", return_value=resp):
            assert client.has_file("owner", "repo", ".gitmodules", "abc123") is True

    def test_returns_false_on_404(self) -> None:
        resp = httpx.Response(404, json={}, request=_FAKE_REQ)
        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", return_value=resp):
            assert client.has_file("owner", "repo", ".gitmodules", "abc123") is False

    def test_raises_on_403(self) -> None:
        resp = httpx.Response(403, json={"message": "forbidden"}, request=_FAKE_REQ)
        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", return_value=resp):
            with pytest.raises(httpx.HTTPStatusError):
                client.has_file("owner", "repo", ".gitmodules", "abc123")


def _make_tarball_bytes(files: dict[str, str], prefix: str = "owner-repo-abc123") -> bytes:
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel_path, content in files.items():
            full = f"{prefix}/{rel_path}"
            data = content.encode()
            info = tarfile.TarInfo(name=full)
            info.size = len(data)
            tar.addfile(info, BytesIO(data))
    return buf.getvalue()


class TestDownloadTarball:
    def test_extracts_and_unwraps(self, tmp_path: Path) -> None:
        tarball_bytes = _make_tarball_bytes({"hello.txt": "world", "src/main.py": "print(1)"})

        class FakeStream:
            def __init__(self) -> None:
                self.status_code = 200

            def raise_for_status(self) -> None:
                pass

            def iter_bytes(self) -> list[bytes]:
                return [tarball_bytes]

            def __enter__(self) -> "FakeStream":
                return self

            def __exit__(self, *args: object) -> None:
                pass

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "stream", return_value=FakeStream()):
            dest = tmp_path / "repo"
            result = client.download_tarball("owner", "repo", "abc123", dest)

        assert result == dest
        assert (dest / "hello.txt").read_text() == "world"
        assert (dest / "src/main.py").read_text() == "print(1)"
        assert not any(tmp_path.glob("*.tar.gz"))
