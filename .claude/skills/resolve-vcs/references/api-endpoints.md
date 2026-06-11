# API Endpoints Reference

## deps.dev

**Version info:**
```
GET https://api.deps.dev/v3alpha/systems/pypi/packages/{name}/versions/{version}
```

Key fields in the response:
- `relatedProjects[]` — array of related project entries
  - `relationType` — e.g. `SOURCE_REPO`, `ISSUE_TRACKER`, `HOMEPAGE`
  - `relationProvenance` — e.g. `UNVERIFIED_METADATA`, `VERIFIED_ATTESTATION`
  - `projectKey.id` — project identifier like `github.com/owner/repo`
- `attestations[]` — array of attestation entries
  - `verified` — boolean, indicates cryptographic verification
  - `sourceRepository` — full URL like `https://github.com/owner/repo`
  - `commit` — 40-char SHA-1

## PyPI

**Version metadata:**
```
GET https://pypi.org/pypi/{name}/{version}/json
```

Key fields in the response:
- `info.project_urls` — dict of label→URL, common labels:
  - `Source`, `Source Code`, `Repository`, `Code`
  - `Homepage`, `Home`, `Home-page`
  - `Bug Tracker`, `Issues`, `Issue Tracker`
  - `Documentation`, `Docs`
  - `Changelog`, `Changes`
- `info.home_page` — legacy homepage URL
- `info.description` — long description (may contain repo links)
- `urls[]` — list of release file entries
  - `packagetype` — `sdist` or `bdist_wheel`
  - `url` — download URL
  - `digests.sha256` — file hash

## GitHub API

**Resolve tag to commit:**
```
GET https://api.github.com/repos/{owner}/{repo}/git/ref/tags/{tag}
```

Response `.object`:
- `type: "commit"` → `.sha` is the commit hash
- `type: "tag"` → annotated tag, dereference via:
  ```
  GET https://api.github.com/repos/{owner}/{repo}/git/tags/{sha}
  ```
  Then `.object.sha` is the commit.

**List recent tags:**
```
GET https://api.github.com/repos/{owner}/{repo}/tags?per_page=10
```

**Check repo exists / follow redirects:**
```
GET https://api.github.com/repos/{owner}/{repo}
```
Returns `full_name` with current owner/repo after redirects.
