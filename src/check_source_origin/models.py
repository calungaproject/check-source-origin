from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FileEntry:
    path: str
    digest: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "digest": self.digest}


@dataclass(frozen=True)
class DiffResult:
    path: str
    sdist_digest: str
    vcs_digest: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "sdist_digest": self.sdist_digest,
            "vcs_digest": self.vcs_digest,
        }


@dataclass(frozen=True)
class DiffReport:
    added: list[FileEntry] = field(default_factory=list)
    removed: list[FileEntry] = field(default_factory=list)
    modified: list[DiffResult] = field(default_factory=list)
    generated: list[FileEntry] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.added) == 0 and len(self.modified) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": {
                "modified": [d.to_dict() for d in self.modified],
                "unexpected": [f.to_dict() for f in self.added],
            },
            "info": {
                "excluded": [f.to_dict() for f in self.removed],
                "generated": [f.to_dict() for f in self.generated],
            },
        }


@dataclass(frozen=True)
class ResolveResult:
    repo_url: str
    commit: str | None
    tag: str | None
    resolution_method: str
    subdir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "repo_url": self.repo_url,
            "commit": self.commit,
            "tag": self.tag,
            "resolution_method": self.resolution_method,
        }
        if self.subdir is not None:
            d["subdir"] = self.subdir
        return d
