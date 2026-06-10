from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path

from .models import DiffReport, DiffResult, FileEntry

GENERATED_PATTERNS: list[str] = [
    "PKG-INFO",
    "*.egg-info/*",
    "*.egg-info",
    "*.dist-info/*",
    "*.dist-info",
    "setup.cfg",
]


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def is_generated(rel_path: str, extra_patterns: list[str] | None = None) -> bool:
    patterns = GENERATED_PATTERNS + (extra_patterns or [])
    for pattern in patterns:
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        parts = rel_path.split("/")
        for part_idx in range(len(parts)):
            sub = "/".join(parts[part_idx:])
            if fnmatch.fnmatch(sub, pattern):
                return True
    return False


def _walk_files(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(root))
            result[rel] = hash_file(p)
    return result


def compare_trees(
    sdist_root: Path,
    vcs_root: Path,
    extra_ignore: list[str] | None = None,
) -> DiffReport:
    sdist_files = _walk_files(sdist_root)
    vcs_files = _walk_files(vcs_root)

    sdist_only = set(sdist_files) - set(vcs_files)
    vcs_only = set(vcs_files) - set(sdist_files)
    common = set(sdist_files) & set(vcs_files)

    added: list[FileEntry] = []
    generated: list[FileEntry] = []
    for path in sorted(sdist_only):
        entry = FileEntry(path=path, digest=sdist_files[path])
        if is_generated(path, extra_ignore):
            generated.append(entry)
        else:
            added.append(entry)

    removed = [
        FileEntry(path=path, digest=vcs_files[path]) for path in sorted(vcs_only)
    ]

    modified: list[DiffResult] = []
    for path in sorted(common):
        if sdist_files[path] == vcs_files[path]:
            continue
        if is_generated(path, extra_ignore):
            generated.append(FileEntry(path=path, digest=sdist_files[path]))
        else:
            modified.append(
                DiffResult(
                    path=path,
                    sdist_digest=sdist_files[path],
                    vcs_digest=vcs_files[path],
                )
            )

    return DiffReport(
        added=added,
        removed=removed,
        modified=modified,
        generated=generated,
    )
