# As-Is

관세사를 위한 원상태수출 재고 매칭 데모입니다. 수입 신고 자료와 수출 예정 자료를 업로드하면 품번, 원산지, 수입 수리일 기준으로 사용 가능한 수입 재고를 찾고 FIFO 방식으로 수출 건에 배정합니다.

This is a local-first FastAPI application for customs refund workflow prototyping. It helps customs brokers and trade operations teams review import inventory, export requirements, matching evidence, and report downloads before preparing an actual refund claim.

## What It Does

- Imports CSV/XLSX import-lot data into a local SQLite database.
- Imports CSV/XLSX export requirement data.
- Shows a preview before confirmed rows are saved.
- Matches exports to import lots by same part number, same origin, import date within 360 days, remaining quantity, and FIFO order.
- Keeps HS-code mismatch as a warning instead of blocking the match.
- Excludes invalidated upload batches from dashboard, inventory, matching, and report totals.
- Downloads allocation evidence and inventory summaries as CSV/XLSX reports.

## Who It Is For

As-Is is designed for:

- customs brokers reviewing 원상태수출 refund evidence,
- trade operations teams managing part-number based import/export inventory,
- developers exploring compliance-oriented inventory matching workflows.

It is not a customs filing system and does not submit data to UNI-PASS or any government service.

## Current Workflow

```text
Upload import lots
  -> Preview and confirm rows
  -> Upload export requirements
  -> Preview and confirm rows
  -> Run FIFO matching
  -> Review inventory and allocation evidence
  -> Download CSV/XLSX reports
```

## Matching Rules

The current matcher uses:

- same part number,
- same origin,
- import accepted date before or on the export date,
- import accepted date within 360 days of the export date,
- remaining quantity greater than zero,
- FIFO order by import accepted date, declaration number, line number, and row number.

If an export HS code differs from the matched import HS code, the allocation is still created with a warning. The warning is evidence for human review; it is not a final legal determination.

## Data And Security Boundary

By default, data stays on the machine running the app:

- The default database is `sqlite:///./as_is.db`.
- The local demo binds to `127.0.0.1:8000`.
- Docker Compose stores SQLite data in the `as_is_data` volume.

Do not upload real customer data to a public demo instance. If you adapt this project for production use, add authentication, authorization, backup policy, audit logging, encryption-at-rest decisions, and a legal review of the matching policy.

## Quick Start

### macOS/Linux

```bash
./start.sh
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### Windows

Double-click `start.bat`, then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

The start scripts prefer `uv`. If `uv` is unavailable, they create a Python virtual environment and install the project with `pip`. Python 3.12 or newer is required.

## Demo Data

Use these files for a practical end-to-end demo:

- `samples/practical_imports.csv`
- `samples/practical_exports.csv`
- `samples/practical_import_review_cases.csv`

Suggested flow:

1. Open `/upload`.
2. Upload `samples/practical_imports.csv` as import data and confirm the preview.
3. Upload `samples/practical_exports.csv` as export requirements and confirm the preview.
4. Open `/exports` and run matching. Leave the date empty to process all pending export requirements.
5. Open `/inventory` to review remaining import quantity.
6. Open `/reports` to download allocation and inventory reports.

To reset local demo data, stop the server and delete `as_is.db`.

## Development

```bash
uv venv --python 3.12
uv sync --extra test
uv run uvicorn app.main:app --reload
```

Without `uv`:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
uvicorn app.main:app --reload
```

## Tests

```bash
uv run pytest
```

or, inside an activated virtual environment:

```bash
pytest
```

## Docker

```bash
docker compose up -d --build
```

The provided compose file expects an external Docker network named `proxy-net`, because it is intended for a reverse-proxy runtime host. For a standalone local Docker demo, either create that network first or adapt the compose file for your environment.

## Reports

The app can download:

- export allocation evidence as CSV,
- a contest-style workbook with inventory and allocation sheets,
- a full workbook with inventory, matching, summary, and part-number inventory views.

## CI/CD

GitHub Actions runs tests on pull requests. On `main` pushes or manual runs, the workflow builds and publishes a Docker image to GitHub Container Registry. SSH deployment requires the repository deployment secrets documented in `.github/workflows/ci-cd.yml`.

## Roadmap

- clearer import/export template documentation,
- reviewer-focused audit trail for matching decisions,
- packaged local desktop shell,
- optional encrypted local database storage,
- production-grade authentication and authorization for hosted use.

## Contributing

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md) for local setup, tests, and pull request expectations.

## Security

Please do not open public issues for sensitive reports. See [SECURITY.md](SECURITY.md) for the current reporting policy and project security boundary.

## License

MIT. See [LICENSE](LICENSE).
