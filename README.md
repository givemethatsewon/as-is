# 처음처럼 - 원상태수출관리 / As-Is

FastAPI, SQLite, Jinja templates 기반 원상태 수출 재고/매칭 MVP입니다.

## Development

```bash
uv venv --python 3.12
source .venv/bin/activate
uv sync --extra test
uv run uvicorn app.main:app --reload
```

앱은 기본적으로 `http://127.0.0.1:8000`에서 실행됩니다. SQLite 파일은 `as_is.db`로 생성됩니다.

## Test

```bash
source .venv/bin/activate
uv run pytest
```

## MVP Flow

1. `/upload`에서 수입 데이터 CSV/XLSX를 preview 후 confirm합니다.
2. `/upload`에서 수출 요청 CSV/XLSX를 preview 후 confirm합니다.
3. `/exports`에서 FIFO 자동 매칭을 실행합니다.
4. `/inventory`에서 잔량을 조회합니다.
5. `/reports`에서 CSV 또는 XLSX 리포트를 다운로드합니다.

