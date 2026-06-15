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

    def test_returns_none_on_301(self) -> None:
        resp = httpx.Response(301, headers={"location": "https://api.github.com/repositories/123/git/ref/tags/v1.0"}, request=_FAKE_REQ)
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

    def test_returns_none_on_301(self) -> None:
        resp = httpx.Response(301, headers={"location": "https://api.github.com/repositories/123/git/tags/abc123"}, request=_FAKE_REQ)
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


def _ref(tag: str, sha: str = "abc123", obj_type: str = "commit") -> dict:
    return {
        "ref": f"refs/tags/{tag}",
        "object": {"type": obj_type, "sha": sha},
    }


def _matching_refs_response(refs: list[dict]) -> httpx.Response:
    return httpx.Response(200, json=refs, request=_FAKE_REQ)


_EMPTY_REFS = httpx.Response(200, json=[], request=_FAKE_REQ)


class TestResolveVersionCommit:
    def test_finds_v_prefixed_tag(self) -> None:
        """Most repos use 'v{version}' tags."""

        def side_effect(url: str, **kwargs: object) -> httpx.Response:
            if "/matching-refs/tags/v1.0.0" in url:
                return _matching_refs_response([_ref("v1.0.0")])
            return _EMPTY_REFS

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", side_effect=side_effect):
            result = client.resolve_version_commit(
                "https://github.com/owner/repo", "1.0.0", "mypkg"
            )
        assert result.commit == "abc123"

    def test_finds_release_prefixed_tag(self) -> None:
        """Repos like apache/avro use 'release-X.Y.Z' tags."""

        def side_effect(url: str, **kwargs: object) -> httpx.Response:
            if "/matching-refs/tags/release-1.12.1" in url:
                return _matching_refs_response([_ref("release-1.12.1")])
            return _EMPTY_REFS

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", side_effect=side_effect):
            result = client.resolve_version_commit(
                "https://github.com/apache/avro", "1.12.1", "avro"
            )
        assert result.commit == "abc123"
        assert result.repo_url == "https://github.com/apache/avro"

    def test_finds_name_underscore_version_tag(self) -> None:
        """Monorepos like azure-sdk-for-python use '{name}_{version}' tags."""

        def side_effect(url: str, **kwargs: object) -> httpx.Response:
            if "/matching-refs/tags/azure-synapse-artifacts_0.22.0" in url:
                return _matching_refs_response(
                    [_ref("azure-synapse-artifacts_0.22.0", sha="def456")]
                )
            return _EMPTY_REFS

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", side_effect=side_effect):
            result = client.resolve_version_commit(
                "https://github.com/Azure/azure-sdk-for-python",
                "0.22.0",
                name="azure-synapse-artifacts",
            )
        assert result.commit == "def456"

    def test_finds_name_hyphen_v_version_tag(self) -> None:
        """Monorepos like pypa/hatch use '{name}-v{version}' tags."""

        def side_effect(url: str, **kwargs: object) -> httpx.Response:
            if "/matching-refs/tags/hatch-v1.16.5" in url:
                return _matching_refs_response(
                    [_ref("hatch-v1.16.5", sha="fed987")]
                )
            return _EMPTY_REFS

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", side_effect=side_effect):
            result = client.resolve_version_commit(
                "https://github.com/pypa/hatch", "1.16.5", name="hatch"
            )
        assert result.commit == "fed987"

    def test_finds_name_double_equals_version_tag(self) -> None:
        """Monorepos like langchain use '{name}=={version}' tags."""

        def side_effect(url: str, **kwargs: object) -> httpx.Response:
            if "/matching-refs/tags/langchain-core==1.4.0" in url:
                return _matching_refs_response(
                    [_ref("langchain-core==1.4.0", sha="aaa111")]
                )
            return _EMPTY_REFS

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", side_effect=side_effect):
            result = client.resolve_version_commit(
                "https://github.com/langchain-ai/langchain",
                "1.4.0",
                name="langchain-core",
            )
        assert result.commit == "aaa111"

    def test_finds_version_suffixed_tag(self) -> None:
        """Monorepos like azure-storage-python use 'v{version}-{suffix}' tags."""

        def side_effect(url: str, **kwargs: object) -> httpx.Response:
            if "/matching-refs/tags/v2.1.0" in url:
                return _matching_refs_response([
                    _ref("v2.1.0-blob", sha="other"),
                    _ref("v2.1.0-common", sha="abc123"),
                    _ref("v2.1.0-storage-common", sha="longer"),
                ])
            return _EMPTY_REFS

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", side_effect=side_effect):
            result = client.resolve_version_commit(
                "https://github.com/Azure/azure-storage-python",
                "2.1.0",
                name="azure-storage-common",
            )
        assert result.commit == "abc123"

    def test_exact_v_version_preferred_over_suffix(self) -> None:
        """When both v{version} and v{version}-{suffix} exist, prefer exact."""

        def side_effect(url: str, **kwargs: object) -> httpx.Response:
            if "/matching-refs/tags/v1.0.0" in url:
                return _matching_refs_response([
                    _ref("v1.0.0", sha="exact"),
                    _ref("v1.0.0-common", sha="suffixed"),
                ])
            return _EMPTY_REFS

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", side_effect=side_effect):
            result = client.resolve_version_commit(
                "https://github.com/owner/repo",
                "1.0.0",
                name="azure-storage-common",
            )
        assert result.commit == "exact"

    def test_suffix_shortest_first(self) -> None:
        """When multiple suffixes match, shortest is preferred."""

        def side_effect(url: str, **kwargs: object) -> httpx.Response:
            if "/matching-refs/tags/v1.0.0" in url:
                return _matching_refs_response([
                    _ref("v1.0.0-b-c", sha="longer"),
                    _ref("v1.0.0-c", sha="shorter"),
                ])
            return _EMPTY_REFS

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", side_effect=side_effect):
            result = client.resolve_version_commit(
                "https://github.com/owner/repo", "1.0.0", name="a-b-c"
            )
        assert result.commit == "shorter"

    def test_stripped_trailing_zero(self) -> None:
        """Repos like jquast/blessed tag '1.43' instead of '1.43.0'."""

        def side_effect(url: str, **kwargs: object) -> httpx.Response:
            if "/matching-refs/tags/1.43" in url and "1.43.0" not in url:
                return _matching_refs_response([_ref("1.43", sha="bbb222")])
            return _EMPTY_REFS

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", side_effect=side_effect):
            result = client.resolve_version_commit(
                "https://github.com/jquast/blessed",
                "1.43.0",
                name="blessed",
            )
        assert result.commit == "bbb222"

    def test_search_order(self) -> None:
        """Prefix searches are tried in the documented order."""
        searched: list[str] = []

        def side_effect(url: str, **kwargs: object) -> httpx.Response:
            if "/matching-refs/tags/" in url:
                prefix = url.split("/matching-refs/tags/", 1)[1]
                searched.append(prefix)
            return _EMPTY_REFS

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", side_effect=side_effect):
            result = client.resolve_version_commit(
                "https://github.com/owner/repo", "1.0.0", "mypkg"
            )
        assert result.commit is None
        assert searched == [
            # Primary search with full version
            "v1.0.0",
            "1.0.0",
            "release-1.0.0",
            "mypkg-v1.0.0",
            "mypkg_1.0.0",
            "mypkg==1.0.0",
            "mypkg-1.0.0",
            # Retry with trailing .0 stripped
            "v1.0",
            "1.0",
            "release-1.0",
            "mypkg-v1.0",
            "mypkg_1.0",
            "mypkg==1.0",
            "mypkg-1.0",
        ]

    def test_search_order_no_strip_when_no_trailing_zero(self) -> None:
        """No stripped-version retry when version doesn't end in .0."""
        searched: list[str] = []

        def side_effect(url: str, **kwargs: object) -> httpx.Response:
            if "/matching-refs/tags/" in url:
                prefix = url.split("/matching-refs/tags/", 1)[1]
                searched.append(prefix)
            return _EMPTY_REFS

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", side_effect=side_effect):
            result = client.resolve_version_commit(
                "https://github.com/owner/repo", "1.0.1", "mypkg"
            )
        assert result.commit is None
        assert searched == [
            "v1.0.1",
            "1.0.1",
            "release-1.0.1",
            "mypkg-v1.0.1",
            "mypkg_1.0.1",
            "mypkg==1.0.1",
            "mypkg-1.0.1",
        ]

    def test_rejects_prerelease_suffix(self) -> None:
        """Tags like v1.0.0rc1 should not match version 1.0.0."""

        def side_effect(url: str, **kwargs: object) -> httpx.Response:
            if "/matching-refs/tags/v1.0.0" in url:
                return _matching_refs_response([_ref("v1.0.0rc1", sha="bad")])
            return _EMPTY_REFS

        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient()
        with patch.object(httpx.Client, "get", side_effect=side_effect):
            result = client.resolve_version_commit(
                "https://github.com/owner/repo", "1.0.0", "mypkg"
            )
        assert result.commit is None


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
