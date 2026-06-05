# Development

## Running tests

```sh
uvx nox -s tests-3.12
```

Run a specific test:

```sh
uvx nox -s tests-3.12 -- tests/test_cli.py::TestPrintDiffReport::test_default_shows_hint
```

## Running all checks (tests, lint, typecheck)

```sh
uvx nox
```

## Testing practices

Follow red/green TDD: write a failing test first, then write the minimum code to make it pass. Run tests after each step to confirm the red→green transition.

## Running the CLI locally

```sh
uvx --with-editable . check-source-origin --help
```
