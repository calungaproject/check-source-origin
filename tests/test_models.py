import json

from check_source_origin.models import DiffReport, DiffResult, FileEntry, ResolveResult


class TestResolveResult:
    def test_creation(self) -> None:
        r = ResolveResult(
            repo_url="https://github.com/pallets/flask",
            commit="abc123",
            tag="3.0.0",
            resolution_method="attestation",
        )
        assert r.repo_url == "https://github.com/pallets/flask"
        assert r.commit == "abc123"
        assert r.tag == "3.0.0"

    def test_to_dict(self) -> None:
        r = ResolveResult(
            repo_url="https://github.com/pallets/flask",
            commit="abc123",
            tag=None,
            resolution_method="pypi_metadata",
        )
        d = r.to_dict()
        assert d["repo_url"] == "https://github.com/pallets/flask"
        assert d["tag"] is None
        json.dumps(d)


class TestDiffReport:
    def test_pass_when_no_diffs(self) -> None:
        report = DiffReport(
            added=[],
            removed=[],
            modified=[],
            generated=[FileEntry(path="PKG-INFO", digest="aaa")],
        )
        assert report.passed is True

    def test_fail_when_added(self) -> None:
        report = DiffReport(
            added=[FileEntry(path="evil.py", digest="bbb")],
            removed=[],
            modified=[],
            generated=[],
        )
        assert report.passed is False

    def test_fail_when_modified(self) -> None:
        report = DiffReport(
            added=[],
            removed=[],
            modified=[
                DiffResult(
                    path="setup.py",
                    sdist_digest="aaa",
                    vcs_digest="bbb",
                )
            ],
            generated=[],
        )
        assert report.passed is False

    def test_removed_only_still_passes(self) -> None:
        report = DiffReport(
            added=[],
            removed=[FileEntry(path=".github/ci.yml", digest="ccc")],
            modified=[],
            generated=[],
        )
        assert report.passed is True

    def test_to_dict(self) -> None:
        report = DiffReport(
            added=[FileEntry(path="x.py", digest="aaa")],
            removed=[FileEntry(path=".github/ci.yml", digest="bbb")],
            modified=[
                DiffResult(path="setup.py", sdist_digest="ccc", vcs_digest="ddd")
            ],
            generated=[FileEntry(path="PKG-INFO", digest="eee")],
        )
        d = report.to_dict()
        assert d["passed"] is False

        assert "issues" in d
        assert len(d["issues"]["unexpected"]) == 1
        assert d["issues"]["unexpected"][0]["path"] == "x.py"
        assert len(d["issues"]["modified"]) == 1
        assert d["issues"]["modified"][0]["path"] == "setup.py"

        assert "info" in d
        assert len(d["info"]["excluded"]) == 1
        assert d["info"]["excluded"][0]["path"] == ".github/ci.yml"
        assert len(d["info"]["generated"]) == 1
        assert d["info"]["generated"][0]["path"] == "PKG-INFO"

        assert "added" not in d
        assert "removed" not in d
        assert "modified" not in d
        assert "generated" not in d

        json.dumps(d)
