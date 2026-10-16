# kvstore-cli

A small, dependency-free Python CLI that stores arbitrary JSON-serialisable
values in a single JSON file. Useful as a starter template for a Python tool
that **builds and tests automatically on GitHub Actions**.

## Features

- `set` / `get` / `delete` / `list` subcommands
- Values are JSON-parsed when possible (so `set nums [1,2,3]` stores a list)
- No third-party runtime dependencies
- Lint (`ruff`) + test (`pytest`) + build (`python -m build`) in CI

## Usage

```bash
pip install -e ".[dev]"

kvstore set name bob
kvstore get name          # "bob"
kvstore set nums "[1,2,3]"
kvstore list
kvstore delete name
```

Use `--db` to point at a different storage file:

```bash
kvstore --db /tmp/my.db set k v
```

## Development

```bash
pip install -e ".[dev]"
ruff check src tests
pytest -q
python -m build
```

## CI

On every push to `main` and on every pull request, GitHub Actions
(`.github/workflows/ci.yml`) runs the build matrix across Python 3.10–3.12:
lint → test → build → upload the distribution as an artifact.
