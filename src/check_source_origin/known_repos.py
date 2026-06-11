from __future__ import annotations

import re

KNOWN_REPOS: dict[str, str] = {
    "adlfs": "https://github.com/fsspec/adlfs",
    "zict": "https://github.com/dask/zict",
}


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def lookup(name: str) -> str | None:
    return KNOWN_REPOS.get(_normalize(name))
