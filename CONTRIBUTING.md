# Contributing

Thanks for considering a contribution to As-Is.

This project is a local-first FastAPI and SQLite demo for customs refund inventory matching workflows. Keep changes small, testable, and explicit about business-rule impact.

## Local Setup

```bash
uv venv --python 3.12
uv sync --extra test
uv run uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

If you do not use `uv`, create a Python 3.12 virtual environment and install the project:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
uvicorn app.main:app --reload
```

## Tests

Run the test suite before opening a pull request:

```bash
uv run pytest
```

or:

```bash
pytest
```

## Pull Request Guidelines

- Explain the workflow impact in the pull request body.
- Add or update tests for matching, upload parsing, reports, or API behavior changes.
- Keep legal/compliance assumptions explicit. Matching output is evidence for review, not a final customs determination.
- Do not include real customer data, private declaration numbers, personal information, credentials, or production URLs.
- Prefer sample fixtures under `samples/` or test fixtures under `tests/`.

## Issue Guidelines

When reporting a bug, include:

- the affected workflow,
- a minimal sample file or row shape,
- expected behavior,
- actual behavior,
- whether the issue affects import preview, export preview, matching, inventory, or reports.

For sensitive reports, follow `SECURITY.md` instead of opening a public issue.
