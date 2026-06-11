# check-source-origin

Verify that a published Python sdist actually matches its claimed VCS source.

Existing tools like `check-sdist` and `check-manifest` help package *authors* ensure they're shipping the right files. `check-source-origin` serves a different purpose: it lets *consumers* verify that an already-published sdist hasn't been tampered with by comparing its contents against the original source repository.

## Install

Requires Python 3.10+ and git. No global install needed — run directly with `uvx`:

```
uvx --from check-source-origin check-source-origin verify flask 3.1.1
```

Or install into a project:

```
uv add check-source-origin
```

## Usage

### Full verification pipeline

```
check-source-origin verify flask 3.1.1
```

Resolves the VCS source, downloads the sdist from PyPI, clones the repo at the matching commit, and diffs every file. Exits with code 1 if any source files were added or modified.

```
check-source-origin verify flask 3.1.1 --json-output
```

### Building blocks

Each step of the pipeline is available as a standalone command:

```sh
# Map a package version to its source repository and commit
check-source-origin resolve flask 3.1.1

# Download the sdist from PyPI (with SHA-256 verification)
check-source-origin download flask 3.1.1 -o flask-3.1.1.tar.gz

# Compare an sdist against a specific repo and ref
check-source-origin diff ./flask-3.1.1.tar.gz \
    --repo https://github.com/pallets/flask \
    --ref 7fff56f5172c48b6f3aedf17ee14ef5c2533dfd1
```

### Options

All commands that produce output support `--json-output` for machine-readable JSON.

The `diff` command accepts `--ignore <pattern>` (repeatable) to treat additional glob patterns as generated/expected files.

The `verify` command accepts `--sdist <path>` to skip the download step and use a pre-downloaded tarball.

### GitHub authentication

The tool uses the GitHub API to resolve tags and commits. Unauthenticated requests are limited to 60 per hour. To avoid rate-limit failures, set a GitHub token:

```sh
export GH_TOKEN=$(gh auth token)
```

The tool checks `GH_TOKEN` first, then `GITHUB_TOKEN`.

## How resolution works

`check-source-origin resolve` maps a package version to its VCS repository using multiple strategies, in priority order:

1. **Verified attestations** — deps.dev cryptographically verified provenance (PyPI publish attestations, SLSA). Returns the exact commit.
2. **Related projects** — deps.dev project associations derived from attestations or metadata.
3. **PyPI metadata heuristics** — `project_urls` and `home_page` fields from PyPI, matched against known VCS hosts (GitHub, GitLab, Bitbucket).

The `verified` field in the output distinguishes cryptographic provenance from best-effort heuristics.

## How diffing works

The `diff` step extracts the sdist, clones the repo at the target ref, and compares every file by SHA-256 digest. Files are classified into four categories:

| Category | Meaning | Affects pass/fail |
|---|---|---|
| **modified** | File exists in both but content differs | Yes |
| **added** | File only in sdist, not in VCS, not on the generated-file allowlist | Yes |
| **removed** | File only in VCS (tests, CI configs, etc. excluded from sdist) | No |
| **generated** | File only in sdist but matches known generated patterns (`PKG-INFO`, `*.egg-info/`, etc.) | No |

## Development

```sh
# Run tests
uvx nox -s tests-3.12

# Run all sessions (tests, lint, typecheck)
uvx nox

# Run the CLI locally
uvx --from . check-source-origin --help
```

## License

MIT
