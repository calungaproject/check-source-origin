---
name: resolve-vcs
description: >-
  Investigate and fix VCS resolution failures for Python packages. Use when
  check-source-origin resolve fails for a package and you need to manually find
  the source repository and add it to the known_repos fallback.
compatibility: Requires internet access, curl, jq, and Python with uv.
allowed-tools: Bash(curl:*) Bash(uvx:*) Bash(grep:*) Bash(jq:*) WebSearch Read
---

# Resolve VCS for a Python package

When `check-source-origin resolve` fails to find the VCS source for a package,
this skill walks through a structured investigation to locate the correct
repository and add it to the hardcoded fallback map.

## Input

The user provides a package name and version, e.g. `somepackage 1.2.3`.

## Workflow

### Phase 1: Confirm the failure

Run the resolve command and confirm it fails:

```
uvx --with-editable . check-source-origin resolve <NAME> <VERSION>
```

If it succeeds, report the result and stop.

### Phase 2: Inspect upstream data

Fetch raw data from the APIs the tool queries. Look at the full responses
carefully — the repo URL may be present under a field our code doesn't check.

#### 2a. deps.dev

```
curl -s "https://api.deps.dev/v3alpha/systems/pypi/packages/<NAME>/versions/<VERSION>" | jq .
```

Examine the full response. Look for:
- `relatedProjects` — any entry with `relationType: SOURCE_REPO`?
- `attestations` — any with `verified: true` and a `sourceRepository`?
- Any other fields that contain repository URLs or project identifiers.

#### 2b. PyPI metadata

```
curl -s "https://pypi.org/pypi/<NAME>/<VERSION>/json" | jq .
```

Examine `info.project_urls`, `info.home_page`, and `info.description` for
repository links. Our code only matches URLs against GitHub, GitLab, and
Bitbucket patterns — the URL might be there but in a non-standard format (e.g.
with a trailing path, a `tree/main` suffix, or a Codeberg/SourceHut host).

Also check `info.project_urls` keys — sometimes the repo is under an unusual
label like `Code`, `Source Code`, `Development`, or `Homepage` rather than the
expected `Source` or `Repository`.

### Phase 3: Web search

If the data from Phase 2 doesn't reveal the repo, search the web:

```
"<NAME>" python package source repository site:github.com OR site:gitlab.com
```

Also try:
- `"<NAME>" python git repository`
- Checking the package's PyPI page description for links
- Checking if the package is a fork or rename of another package

### Phase 4: Verify the candidate repository

Once you have a candidate repo URL, verify it:

1. **Check the repo exists** — `curl -s -o /dev/null -w '%{http_code}' <REPO_URL>`
2. **Check tag patterns** — look for version tags that match the package version:
   ```
   curl -s "https://api.github.com/repos/<OWNER>/<REPO>/git/ref/tags/v<VERSION>"
   curl -s "https://api.github.com/repos/<OWNER>/<REPO>/git/ref/tags/<VERSION>"
   ```
   The tool tries `v<VERSION>` first, then `<VERSION>`. If neither exists, check
   what tag format the repo actually uses:
   ```
   curl -s "https://api.github.com/repos/<OWNER>/<REPO>/tags?per_page=10" | jq -r '.[].name'
   ```
3. **Sanity-check the package name** — confirm the repo's `pyproject.toml` or
   `setup.py` declares the expected package name.

### Phase 5: Report findings

Before making any changes, present a summary to the user:

- What was found at each phase
- The candidate repo URL and evidence supporting it
- Whether the tag pattern matches (`v<VERSION>` or `<VERSION>`)
- Any concerns (e.g., the repo is archived, tag doesn't exist for this version)

Ask the user to confirm before proceeding.

### Phase 6: Add to known_repos

Edit `src/check_source_origin/known_repos.py` and add the new entry to the
`KNOWN_REPOS` dict. The key must be the normalized package name (lowercase,
hyphens instead of underscores/dots). Keep the dict sorted alphabetically.

### Phase 7: Verify the fix

Run the resolve command again to confirm it succeeds:

```
uvx --with-editable . check-source-origin resolve <NAME> <VERSION>
```

Then run the test suite to make sure nothing is broken:

```
uvx nox -s tests-3.12
```

## Notes

- The `KNOWN_REPOS` dict is a last-resort fallback. If you discover that the
  repo URL _is_ present in deps.dev or PyPI data but under a field or format
  our code doesn't handle, consider fixing the parsing logic instead. Report
  this finding to the user so they can decide.
- For GitLab or Bitbucket repos, the `GitHubClient.resolve_version_commit`
  method won't be able to resolve the tag to a commit. The repo URL will still
  be stored but the commit will be `None`. Note this when reporting.
- Multiple packages can share the same repository (monorepos). Verify the
  specific package lives in the candidate repo before adding the mapping.
