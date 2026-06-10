from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

# Only read pyproject.toml from the VCS checkout, never from the sdist.
# Files like setup.cfg are already in GENERATED_PATTERNS and could be
# tampered with in the sdist. The VCS copy is the trusted source of truth.
_PYPROJECT = "pyproject.toml"


def _get(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)  # type: ignore[assignment]
        if data is None:
            return None
    return data


def detect_generated_files(vcs_root: Path) -> list[str]:
    """Return version-file paths declared by build tools in pyproject.toml.

    Must only be called with a VCS (source repo) root — never an sdist root.
    """
    pyproject = vcs_root / _PYPROJECT
    if not pyproject.is_file():
        return []

    try:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return []

    paths: list[str] = []

    scm = _get(data, "tool", "setuptools_scm")
    if isinstance(scm, dict):
        for key in ("version_file", "write_to"):
            val = scm.get(key)
            if isinstance(val, str):
                paths.append(val)

    versioningit_file = _get(data, "tool", "versioningit", "write", "file")
    if isinstance(versioningit_file, str):
        paths.append(versioningit_file)

    hatch_vcs_file = _get(data, "tool", "hatch", "build", "hooks", "vcs", "version-file")
    if isinstance(hatch_vcs_file, str):
        paths.append(hatch_vcs_file)

    pdm = _get(data, "tool", "pdm", "version")
    if isinstance(pdm, dict) and pdm.get("source") != "file":
        val = pdm.get("write_to")
        if isinstance(val, str):
            paths.append(val)

    seen: set[str] = set()
    unique: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique
