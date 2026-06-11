from __future__ import annotations

from check_source_origin.known_repos import KnownRepo, lookup


class TestLookup:
    def test_exact_match(self) -> None:
        result = lookup("adlfs")
        assert result is not None
        assert result.url == "https://github.com/fsspec/adlfs"
        assert result.subdir is None

    def test_case_insensitive(self) -> None:
        result = lookup("ADLFS")
        assert result is not None
        assert result.url == "https://github.com/fsspec/adlfs"

    def test_hyphen_underscore_normalization(self) -> None:
        result = lookup("some-package")
        assert result == lookup("some_package")

    def test_unknown_package(self) -> None:
        assert lookup("nonexistent-pkg-xyz") is None

    def test_monorepo_with_subdir(self) -> None:
        result = lookup("avro")
        assert result is not None
        assert result.url == "https://github.com/apache/avro"
        assert result.subdir == "lang/py"
