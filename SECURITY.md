# Security Policy

## 인증과 trust boundary

- 공용 운영 계정 하나를 사용하며 개인별 role/권한은 제공하지 않습니다.
- `APP_PASSWORD_HASH`는 PBKDF2-SHA256 hash만 저장합니다. 평문 비밀번호를 repository, Docker Compose, CI log에 넣지 않습니다.
- session은 `SESSION_SECRET`으로 서명되고 HttpOnly, SameSite=Lax, 운영 기본 Secure cookie를 사용합니다.
- `/health`, `/login`, `/static/*` 외 route는 인증을 요구합니다.
- 상태 변경 요청은 session CSRF token을 검증하고 로그인 실패는 IP 단위로 제한합니다.
- TLS 종료 reverse proxy 바깥에서 애플리케이션 port를 직접 공개하지 않습니다.

공용 계정이므로 기록되는 행위 주체는 개인 사용자가 아니라 동일한 운영 계정입니다. 개인별 책임 추적이 필요하면 별도 identity/role 설계가 필요합니다.

## 데이터와 파일

- SQLite와 업로드 원본은 Docker volume `/data`에 보존됩니다.
- `.xlsm`은 ZIP 기반 workbook 데이터만 읽고 VBA를 실행하지 않습니다.
- 허용 확장자는 `.xlsx`, `.xlsm`, `.csv`이며 기본 최대 크기는 100 MiB입니다.
- 원본 다운로드는 인증된 batch ID를 통해서만 제공됩니다.
- 공개 demo에는 실제 고객 신고 자료, 개인정보, credential을 올리지 않습니다.

## 운영

- 운영 배포 전에 `.env`에 강한 `SESSION_SECRET`과 공용 계정 hash를 설정합니다.
- 데모 reset은 backup을 먼저 만들고 명시적 `--yes`가 있을 때만 workflow data를 삭제합니다.
- SQLite backup, volume 접근권한, retention 정책은 host 운영자가 관리합니다.
- 이 시스템은 세관 신고를 제출하지 않으며 결과는 자격 있는 담당자가 검토해야 합니다.

## 취약점 제보

민감한 report를 공개 GitHub issue로 올리지 마세요. GitHub Security Advisory 또는 maintainer의 비공개 연락 수단으로 affected commit, 재현 단계, 영향 범위와 데이터 노출 여부를 보내주세요.
