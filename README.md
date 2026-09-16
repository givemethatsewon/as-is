# As-Is

원상태수출 Excel 매크로를 대체하는 수입 재고·수출 FIFO 매칭 워크벤치입니다. 수입 재고를 누적하고, 수출 파일별 배정 결과를 검토한 뒤 명시적으로 확정하며, 결과 Excel과 원본 파일을 다시 받을 수 있습니다.

## 업무 흐름

```text
수입 Excel 업로드 → 신규/중복/충돌 검토 → 재고 누적 확정
수출 Excel 업로드 → 백그라운드 배정 → 행별 FIFO 근거/부족 검토
→ 파일 전체 확정 → 결과 Excel 다운로드 → 필요 시 파일 전체 되돌리기
```

- 정확히 같은 수입 로트는 건너뜁니다.
- 같은 business key에 다른 값이 있으면 수입 파일 전체를 차단합니다.
- 미리보기는 재고를 변경하지 않습니다.
- 수출 확정과 파일 단위 되돌리기는 각각 하나의 SQLite transaction입니다.
- 원본 `.xlsx`, `.xlsm`, `.csv`를 보관하며 VBA는 실행하지 않습니다.

## 매칭 규칙

- Part Number에서 일반 공백, NBSP, tab, CR, LF를 제거한 뒤 대문자로 비교
- 매칭 eligibility는 정규화된 Part Number equality 하나뿐
- 남은 수량이 0보다 큰 로트만 사용
- `신고일자` → `수입신고번호` → `란번호2` → `행번호` 순 FIFO
- 여러 수입 로트로 분할 가능
- 부족하면 가용 배정은 유지하고 `NO MATCH` 행 추가
- `원산지`, `세번`, date, `규격2`, `수량단위_1`은 매칭 key가 아니며 결과 증빙 값으로 보존

## 실행 설정

Python 3.12 이상이 필요합니다. 공용 계정은 환경변수 없이는 구성되지 않으며, 모든 비공개 route는 로그인 세션을 요구합니다.

```bash
cp .env.example .env
python -c 'from app.auth import hash_password; print(hash_password("원하는-비밀번호"))'
openssl rand -hex 32
```

출력값으로 `.env`의 `APP_PASSWORD_HASH`, `SESSION_SECRET`을 교체한 뒤 실행합니다. PBKDF2 hash에는 `$`가 들어가므로 Compose가 재해석하지 않도록 hash 전체를 single quote로 감싸야 합니다.

```dotenv
APP_PASSWORD_HASH='pbkdf2_sha256$...$...$...'
```

```bash
uv venv --python 3.12
uv sync --extra test
set -a && source .env && set +a
UPLOAD_DIR=./data/uploads COOKIE_SECURE=false uv run uvicorn app.main:app --reload
```

`COOKIE_SECURE=false`는 `http://127.0.0.1` 로컬 개발에서만 사용합니다. 운영에서는 TLS reverse proxy와 `COOKIE_SECURE=true`를 유지합니다.

## Docker

```bash
cp .env.example .env
# .env의 공용 계정 hash와 session secret을 교체
docker compose up -d --build
```

Compose는 SQLite와 원본 업로드를 `/data` volume에 보존하며 외부 `proxy-net` network를 사용합니다.

## 데모 데이터 초기화

초기화는 공용 계정 설정(`app_settings`)은 유지하고, 업로드·재고·수출·배정 이력만 지웁니다. 기본적으로 SQLite backup을 먼저 만듭니다.

```bash
ssh <서버 별칭 또는 사용자@호스트>
cd <DEPLOY_PATH>
docker compose exec -T as-is python scripts/reset_demo.py --yes --purge-uploads
docker compose exec -T as-is python -c 'import sqlite3; c=sqlite3.connect("/data/as_is.db"); print({t:c.execute(f"select count(*) from {t}").fetchone()[0] for t in ["import_lots","export_requirements","export_allocations","upload_batches"]})'
```

Backup은 volume의 `/data/backups/as_is-<UTC timestamp>.db`에 남습니다.

## 테스트

```bash
uv run pytest
```

테스트에는 실제 100,000행 CSV를 background preview로 처리하고 review API가 50행만 반환하는 회귀 검증이 포함됩니다. 2026-09-16 Apple Silicon 로컬 측정은 약 28.3초, Python traced peak memory 약 42.9 MiB였습니다. 환경에 따라 달라질 수 있습니다.

## 결과 Excel

- `수출 결과`: `수출 문서`와 `수입 문서`의 원본 10개 header를 그대로 반복하고 `차감 전 수량`, `차감 수량`, `차감 후 잔량`, `미배정 수량`을 연결합니다.
- `원상태잔량`: 수입 문서 원본 10개 header와 `차감 수량`, `차감 후 잔량`을 제공합니다.

본 도구는 UNI-PASS 제출이나 법률·세무 판단을 자동화하지 않습니다.

## CI/CD

Pull request에서는 tests를 실행합니다. `main` push에서는 tests → GHCR image build → SSH host의 `docker compose up -d --build` 순으로 배포합니다. 배포 host의 `<DEPLOY_PATH>/.env`에 `APP_USERNAME`, `APP_PASSWORD_HASH`, `SESSION_SECRET`이 먼저 설정되어 있어야 합니다.
