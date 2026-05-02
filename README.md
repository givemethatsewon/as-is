# 처음처럼 - 원상태수출관리 / As-Is

FastAPI, SQLite, Jinja templates 기반 원상태 수출 재고/매칭 데모 웹입니다.

## 2분 시연 방법

### Windows

1. 이 폴더에서 `start.bat`을 더블클릭합니다.
2. 브라우저에서 `http://127.0.0.1:8000`을 엽니다.

`uv`가 있으면 자동으로 가상환경과 의존성을 준비합니다. `uv`가 없으면 Python 3.12 이상으로 `.venv`를 만들고 필요한 패키지를 설치합니다.

### macOS/Linux

```bash
./start.sh
```

## 업로드 순서

1. `/upload`에서 `samples/import_sample.csv`를 수입 데이터로 업로드하고 미리보기에서 `신규 행 저장하기`를 누릅니다.
2. 같은 화면에서 `samples/export_contest_sample.csv`를 수출 요청으로 업로드하고 저장합니다.
3. `/exports`에서 `선택한 조건으로 매칭하기`를 누릅니다. 날짜를 비우면 매칭 대기 중인 모든 수출 요청을 처리합니다.
4. `/inventory`에서 수입신고별 잔량을 확인합니다.
5. `/reports`에서 `공모전 예시 양식 출력` 또는 `전체 엑셀 파일로 내려받기`를 누릅니다.

## 공모전 핵심 포인트

- 수출 업로드는 공모전 예시 헤더인 `Part Number`, `Description`, `U/Price`, `Ready to Ship`, `Qty`, `Amount`를 수정 없이 인식합니다.
- 미리보기 화면에서 원본 컬럼이 내부 표준 필드에 어떻게 연결됐는지 확인할 수 있습니다.
- 매칭 기준은 `품번 동일 + 원산지 동일 + 360일 이내 + 잔량 > 0 + FIFO`입니다.
- HS 코드가 다르면 매칭은 진행하고 경고를 남기는 정책입니다.
- 무효 처리된 업로드에서 생성된 본 데이터는 이후 대시보드, 재고, 매칭, 리포트 집계에서 제외됩니다.

## 다운로드 파일

- `매칭 결과 CSV로 내려받기`: 수출 건별 수입근거를 CSV로 내려받습니다.
- `공모전 예시 양식 출력`: `수출 전 확인용 잔량표`, `수출 건별 수입근거 자동기재표` 2개 시트로 예시 양식에 가까운 결과를 내려받습니다.
- `전체 엑셀 파일로 내려받기`: 잔량, 매칭, 요약, 품번별 재고 요약을 포함한 상세 리포트입니다.

## CI/CD

GitHub Actions 워크플로는 `.github/workflows/ci-cd.yml`에 있습니다.

- Pull request: Python 3.12로 테스트를 실행합니다.
- `main` push 또는 수동 실행: 테스트 통과 후 Docker 이미지를 `ghcr.io/givemethatsewon/as-is:latest`와 커밋 SHA 태그로 발행합니다.

원격 서버에서 갱신할 때는 아래처럼 GHCR 이미지를 받거나, 현재 `docker-compose.yml`을 서버에서 다시 빌드해 실행합니다.

```bash
docker pull ghcr.io/givemethatsewon/as-is:latest
docker compose up -d
```

## 삭제, 저장, 무효 처리

- 삭제: 저장 전 미리보기 기록만 제거합니다.
- 저장: 미리보기에서 신규로 분류된 행을 본 데이터로 반영합니다.
- 무효 처리: 저장 완료 업로드를 이력으로 남기되, 해당 업로드에서 생성된 본 데이터는 이후 계산과 다운로드에서 제외합니다.

## 오류 대응

- `Python 3.12 이상 또는 uv가 필요합니다`: Python 3.12+ 또는 `uv`를 설치한 뒤 다시 실행합니다.
- 업로드 오류가 나면 미리보기의 `파일 컬럼 연결 결과`와 `수정이 필요한 오류`를 확인합니다.
- 포트가 이미 사용 중이면 명령 프롬프트에서 `set PORT=8001` 실행 후 `start.bat`을 다시 실행합니다.
- 데이터를 처음부터 다시 시연하려면 서버를 끄고 `as_is.db` 파일을 삭제한 뒤 다시 실행합니다.

## 개발

```bash
uv venv --python 3.12
uv sync --extra test
uv run uvicorn app.main:app --reload
```

## 테스트

```bash
uv run pytest
```
