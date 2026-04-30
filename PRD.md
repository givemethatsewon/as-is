아래는 **Codex에게 바로 줄 수 있는 PRD 초안**이야.
웹프로그램 기준으로 작성했고, 이름은 요청대로 **처음처럼 - 원상태수출관리 / As-Is** 로 잡았어.

---

# PRD: 처음처럼 - 원상태수출관리

**English Name:** As-Is
**Product Type:** Web Application
**Goal:** 수입 물품의 원상태 수출 가능 여부, 잔량, 수출 매칭 내역을 자동 관리하는 웹 기반 관세환급 관리 시스템

---

## 1. 제품 개요

**처음처럼 - 원상태수출관리(As-Is)** 는 수입 후 원상태 그대로 360일 이내에 수출되는 물품의 관세환급 관리를 자동화하는 웹 프로그램이다.

기존 업무는 엑셀 기반으로 수입신고번호, 수리일자, 원산지, HS 코드, Part Number, 수량, 잔량, 수출 매칭 정보를 수기로 관리해야 해서 오류가 발생하기 쉽다. 특히 자동차 부품처럼 품목 수가 많고 수입 건이 수만 건까지 늘어나는 경우, 담당자가 어떤 수입 건에서 어떤 수출 건을 차감했는지 추적하기 어렵다. 요구사항 문서에서도 수기 관리의 한계와 자동화된 시스템 필요성이 강조되어 있다.

이 프로그램은 수입 데이터와 수출 요청 데이터를 업로드하면, 조건에 맞는 수입 재고를 자동으로 찾아 FIFO 방식으로 차감하고, 환급 신청에 필요한 매칭 결과를 생성한다.

---

## 2. 핵심 문제

사용자는 수출 전에 다음 정보를 빠르게 알아야 한다.

1. 해당 품번의 잔량이 존재하는가?
2. 해당 품번의 잔량이 얼마인가?
3. 해당 품번은 지금까지 얼마나 수출되었는가?
4. 이번 수출 물량은 어떤 수입신고 건에서 차감해야 하는가?
5. 해당 수입 건은 360일 이내 원상태 수출 조건을 만족하는가?

요구사항상 수출 전 특정 품번의 잔량, 수출량, 사용 가능 여부를 파악할 수 있어야 한다.

---

## 3. 사용자

### Primary User

수출입/관세환급 실무 담당자

### User Needs

- 수입 재고를 품번, 원산지, HS 코드 기준으로 조회하고 싶다.
- 수출 요청 수량을 넣으면 자동으로 어떤 수입 건에서 차감할지 알고 싶다.
- FIFO 방식으로 먼저 들어온 재고부터 자동 차감하고 싶다.
- 360일 초과 재고는 환급 대상에서 제외하고 싶다.
- 환급 신청용 매칭 리포트를 다운로드하고 싶다.

---

## 4. MVP 범위

### 포함

- CSV/XLSX 업로드
- 수입 데이터 등록
- 수출 요청 데이터 등록
- 품번 + 원산지 기준 잔량 조회
- 360일 유효기간 검증
- FIFO 자동 매칭
- 분할 수출 매칭
- 소진 재고 처리
- 수출-수입 매칭 결과 생성
- CSV/XLSX 다운로드
- 대시보드

### 제외

- UNI-PASS API 실시간 연동
- OCR 자동 입력
- 실제 세관 제출 자동화
- 로그인/권한 관리 고도화
- 결제/구독 기능

---

## 5. 데이터 입력

사용자는 다음 데이터를 업로드한다.

### 5.1 수입 데이터 Import Lots

CSV 또는 XLSX 형식.

필수 컬럼:

```text
import_declaration_no
import_accepted_date
origin
hs_code
line_no
row_no
part_number
spec
import_qty
qty_unit
```

예시:

```csv
import_declaration_no,import_accepted_date,origin,hs_code,line_no,row_no,part_number,spec,import_qty,qty_unit
4397825100118M,2025-01-16,CN,8708309000,004,02,MTG011114,STEERING RACK,1256,PC
4397825100118M,2025-03-16,KR,8708309000,004,05,IN565001J100,R/P_GEAR_ASSY,43,PC
```

수입 데이터에는 수입신고번호, 수입신고 수리일, 원산지, HS 코드, 란번호, 행번호, Part Number, 수량 등이 포함된다. 설명 자료에서도 이 값들이 수입신고 건과 품목을 식별하는 핵심 정보로 설명되어 있다.

---

### 5.2 수출 요청 데이터 Export Requirements

필수 컬럼:

```text
export_date
origin
part_number
required_qty
description
unit_price
```

예시:

```csv
export_date,origin,part_number,required_qty,description,unit_price
2025-08-16,CN,MTG011114,800,STEERING RACK,3
2025-08-16,KR,IN565001J100,20,R/P_GEAR_ASSY,4
2025-12-16,CN,MTG011114,800,STEERING RACK,3
2025-12-16,KR,IN565001J100,20,R/P_GEAR_ASSY,4
```

---

## 6. 핵심 기능 요구사항

## FR-1. 수입 데이터 업로드

사용자는 CSV 또는 XLSX 파일을 업로드할 수 있다.

### Acceptance Criteria

- 필수 컬럼이 없으면 업로드 실패 처리한다.
- 날짜 형식은 `YYYY-MM-DD`로 정규화한다.
- 수량은 숫자로 변환한다.
- 중복 수입 건은 `import_declaration_no + line_no + row_no + part_number + origin` 기준으로 식별한다.
- 업로드 후 전체 수입 수량, 사용 수량, 잔량을 계산한다.

---

## FR-2. 수출 요청 업로드

사용자는 수출일자별 필요 수량 데이터를 업로드할 수 있다.

### Acceptance Criteria

- 수출일자, 원산지, Part Number, 필요수량은 필수다.
- 필요수량이 0 이하이면 오류 처리한다.
- 동일 수출일자에 같은 품번과 원산지가 여러 번 들어오면 합산하거나 별도 row로 처리할 수 있어야 한다.

---

## FR-3. 원산지 조건 검증

수출 요청의 원산지와 수입 재고의 원산지가 반드시 같아야 한다.

예를 들어 수출 요청이 `CN + MTG011114` 이면, `KR + MTG011114` 재고는 사용할 수 없다. 요구사항에서도 Part Number만 일치해서는 안 되고 원산지가 반드시 일치해야 한다고 명시되어 있다.

### Acceptance Criteria

- `part_number`가 같아도 `origin`이 다르면 매칭 대상에서 제외한다.
- 제외된 재고는 매칭 결과에 포함하지 않는다.
- 사용자가 조회 시 “원산지 불일치 재고”를 별도로 볼 수 있다.

---

## FR-4. 360일 유효기간 검증

수입신고 수리일로부터 수출일자까지 360일 이내인 재고만 환급 가능 대상으로 본다.

### Rule

```text
export_date - import_accepted_date <= 360 days
```

360일 이내 원상태 수출이어야 관세 환급 대상이 된다는 조건은 공모전 설명과 강의 녹취에서 반복적으로 설명된다.

### Acceptance Criteria

- 360일 초과 재고는 자동 매칭 대상에서 제외한다.
- 360일 초과 재고는 상태를 `expired`로 표시한다.
- 30일 이내 만료 예정 재고는 `expiring_soon`으로 표시한다.

---

## FR-5. FIFO 자동 매칭

조건에 맞는 수입 재고가 여러 개 있으면 먼저 수입된 재고부터 차감한다.

정렬 기준:

```text
import_accepted_date ASC
import_declaration_no ASC
line_no ASC
row_no ASC
```

요구사항 문서에서 선입선출(FIFO) 기반 자동 수량 차감이 핵심 기능으로 제시되어 있다.

### Acceptance Criteria

- 같은 품번 + 원산지 + 유효기간 조건을 만족하는 재고 중 가장 오래된 수입 건부터 사용한다.
- 한 수입 건의 잔량이 부족하면 다음 수입 건으로 넘어간다.
- 매칭 후 각 수입 건의 잔량이 갱신된다.

---

## FR-6. 분할 수출 매칭

하나의 수출 요청 수량을 하나의 수입 건으로 충당할 수 없으면 여러 수입 건으로 나누어 매칭한다.

예시:

```text
수출 필요수량: 800
수입 lot A 잔량: 456
수입 lot B 잔량: 1256

결과:
A에서 456 차감
B에서 344 차감
```

분할 수출 대응은 실무 완성도를 높이는 추가 핵심 기능으로 설명되어 있다.

### Acceptance Criteria

- 하나의 export requirement가 여러 allocation row로 나뉠 수 있다.
- 각 allocation row에는 사용된 수입신고번호, 수리일, 원산지, HS 코드, 란번호, 행번호, 차감 수량이 기록된다.
- 전체 allocation 수량 합계는 required_qty와 같아야 한다.
- 재고가 부족하면 `partial_matched` 또는 `insufficient_stock` 상태를 표시한다.

---

## FR-7. 소진 재고 차단

잔량이 0이 된 수입 재고는 더 이상 매칭 대상이 되면 안 된다.

요구사항에서 잔량 0이 된 데이터는 제외하거나 “사용할 수 없다”로 표시해야 한다고 명시되어 있다.

### Acceptance Criteria

- `remaining_qty = 0`인 lot은 자동 매칭 후보에서 제외한다.
- UI에서는 상태를 `used_up`으로 표시한다.
- 이미 소진된 lot을 수동으로 선택하려 하면 오류를 표시한다.

---

## FR-8. 수입-수출 매칭 결과 자동 기재

수출 결과 테이블에는 어떤 수입 건에서 차감되었는지 자동으로 표시되어야 한다.

출력 필드:

```text
export_date
part_number
description
unit_price
required_qty
amount
matched_qty
import_declaration_no
import_accepted_date
origin
hs_code
line_no
row_no
remaining_qty_after
match_status
```

요구사항 문서에서는 수출 내역 표의 빈칸에 수입신고번호, 수리일, 세번, 란번호, 행번호가 자동 기재되어야 한다고 설명한다.

---

## FR-9. 잔량 조회 대시보드

사용자는 특정 Part Number와 원산지를 입력해 현재 상태를 조회할 수 있다.

### 표시 항목

```text
Part Number
Origin
Total Imported Qty
Total Exported Qty
Remaining Qty
Available Qty
Expired Qty
Used Up Lots Count
Expiring Soon Lots Count
```

### Acceptance Criteria

- 품번만 입력하면 원산지별 잔량을 보여준다.
- 품번 + 원산지를 입력하면 해당 조건의 상세 lot 목록을 보여준다.
- 수출 전 사용 가능한 수량과 이미 수출된 수량을 보여준다.

---

## FR-10. HS 코드 검증

Part Number와 Origin이 같더라도 HS 코드가 다르면 경고를 표시한다.

HS 코드 10자리 일치성 검증은 환급 거절 리스크를 줄이는 추가 기능으로 제안되어 있다.

### Acceptance Criteria

- 수입 lot 간 동일 Part Number인데 HS 코드가 여러 개이면 warning 표시.
- 수출 요청 데이터에 HS 코드가 포함된 경우 수입 HS 코드와 비교한다.
- HS 코드 불일치 시 자동 매칭은 가능하되, 결과에 `hs_code_warning`을 표시한다.
- 설정에서 HS 코드 불일치 시 매칭 차단 옵션을 켤 수 있다.

---

## FR-11. 예상 환급액 계산

수입 데이터에 개당 관세액 또는 총 납부 관세액이 있으면 예상 환급액을 계산한다.

### Optional Columns

```text
duty_per_unit
total_duty_paid
```

### Calculation

```text
expected_refund_amount = matched_qty * duty_per_unit
```

환급 예상액 자동 계산은 단순 수량 관리에서 실무 가치가 높은 기능으로 제안되어 있다.

---

## FR-12. 결과 다운로드

사용자는 결과를 CSV 또는 XLSX로 다운로드할 수 있다.

### 다운로드 파일

1. `import_lots_with_remaining.csv`
2. `export_match_allocations.csv`
3. `dashboard_summary.csv`
4. `refund_report.xlsx`

### Acceptance Criteria

- 매칭 결과 파일은 관세사/세관 제출용으로 읽기 쉬워야 한다.
- XLSX는 시트별로 구분한다.
- CSV는 개발 및 DB 적재용으로 제공한다.

---

## 7. 데이터 모델

## 7.1 import_lots

```sql
CREATE TABLE import_lots (
  id UUID PRIMARY KEY,
  import_declaration_no TEXT NOT NULL,
  import_accepted_date DATE NOT NULL,
  origin TEXT NOT NULL,
  hs_code TEXT NOT NULL,
  line_no TEXT NOT NULL,
  row_no TEXT NOT NULL,
  part_number TEXT NOT NULL,
  spec TEXT,
  import_qty INTEGER NOT NULL,
  qty_unit TEXT,
  used_qty INTEGER NOT NULL DEFAULT 0,
  remaining_qty INTEGER NOT NULL,
  duty_per_unit NUMERIC,
  status TEXT NOT NULL DEFAULT 'available',
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---

## 7.2 export_requirements

```sql
CREATE TABLE export_requirements (
  id UUID PRIMARY KEY,
  export_date DATE NOT NULL,
  origin TEXT NOT NULL,
  part_number TEXT NOT NULL,
  description TEXT,
  unit_price NUMERIC,
  required_qty INTEGER NOT NULL,
  amount NUMERIC,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---

## 7.3 export_allocations

```sql
CREATE TABLE export_allocations (
  id UUID PRIMARY KEY,
  export_requirement_id UUID NOT NULL REFERENCES export_requirements(id),
  import_lot_id UUID NOT NULL REFERENCES import_lots(id),
  matched_qty INTEGER NOT NULL,
  remaining_qty_after INTEGER NOT NULL,
  expected_refund_amount NUMERIC,
  match_status TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---

## 8. 핵심 알고리즘

## 8.1 FIFO Matching Algorithm

```python
def allocate_export(export_req, import_lots):
    candidates = import_lots.filter(
        part_number=export_req.part_number,
        origin=export_req.origin,
        remaining_qty__gt=0,
        import_accepted_date__lte=export_req.export_date,
    )

    candidates = [
        lot for lot in candidates
        if (export_req.export_date - lot.import_accepted_date).days <= 360
    ]

    candidates.sort(key=lambda lot: (
        lot.import_accepted_date,
        lot.import_declaration_no,
        lot.line_no,
        lot.row_no,
    ))

    required = export_req.required_qty
    allocations = []

    for lot in candidates:
        if required <= 0:
            break

        matched_qty = min(required, lot.remaining_qty)

        lot.remaining_qty -= matched_qty
        lot.used_qty += matched_qty
        required -= matched_qty

        allocations.append({
            "export_requirement_id": export_req.id,
            "import_lot_id": lot.id,
            "matched_qty": matched_qty,
            "remaining_qty_after": lot.remaining_qty,
        })

        if lot.remaining_qty == 0:
            lot.status = "used_up"

    if required == 0:
        export_req.status = "matched"
    elif required < export_req.required_qty:
        export_req.status = "partial_matched"
    else:
        export_req.status = "insufficient_stock"

    return allocations
```

---

## 9. 화면 구성

## 9.1 Upload Page

경로:

```text
/upload
```

기능:

- 수입 데이터 업로드
- 수출 요청 데이터 업로드
- 컬럼 매핑 확인
- 업로드 전 validation preview

---

## 9.2 Dashboard Page

경로:

```text
/dashboard
```

표시:

- 전체 수입 수량
- 전체 수출 매칭 수량
- 전체 잔량
- 사용 가능 재고
- 소진 재고
- 360일 초과 재고
- 30일 이내 만료 예정 재고

---

## 9.3 Inventory Page

경로:

```text
/inventory
```

기능:

- Part Number 검색
- Origin 필터
- HS Code 필터
- 상태 필터: available / used_up / expired / expiring_soon
- lot별 잔량 확인

---

## 9.4 Export Matching Page

경로:

```text
/exports
```

기능:

- 수출 요청 목록
- 자동 매칭 실행
- 매칭 결과 확인
- 부족 수량 확인
- 수동 재매칭 옵션

---

## 9.5 Report Page

경로:

```text
/reports
```

기능:

- 수출일자별 매칭 리포트
- Part Number별 잔량 리포트
- 환급 예상액 리포트
- CSV/XLSX 다운로드

---

## 10. 상태 정의

## Import Lot Status

```text
available      사용 가능
used_up        잔량 0
expired        360일 초과
expiring_soon  30일 이내 만료 예정
blocked        수동 차단
```

## Export Requirement Status

```text
pending             매칭 전
matched             전체 매칭 완료
partial_matched     일부만 매칭
insufficient_stock  재고 부족
cancelled           취소
```

---

## 11. Validation Rules

| Rule             | Description                   |
| ---------------- | ----------------------------- |
| Part Number 필수 | 비어 있으면 업로드 실패       |
| Origin 필수      | 비어 있으면 업로드 실패       |
| Import Date 필수 | 날짜 변환 실패 시 업로드 실패 |
| Export Date 필수 | 날짜 변환 실패 시 업로드 실패 |
| Quantity > 0     | 수량은 1 이상                 |
| Origin Match     | 원산지 불일치 재고 제외       |
| 360-day Rule     | 360일 초과 재고 제외          |
| FIFO             | 오래된 수입 건부터 차감       |
| Remaining Qty    | 0 미만 불가                   |
| Duplicate Lot    | 중복 lot 감지                 |

---

## 12. 기술 스택 제안

Codex 구현용 기본 스택:

```text
Frontend: Next.js + TypeScript + Tailwind CSS
Backend: FastAPI + Python
Database: SQLite for MVP, PostgreSQL for production
Data Processing: Pandas
File Export: openpyxl, csv
Testing: pytest
```

MVP에서는 SQLite로 빠르게 만들고, 이후 PostgreSQL로 전환한다.

---

## 13. API 설계

## POST /api/imports/upload

수입 데이터 업로드.

Response:

```json
{
  "uploaded_count": 8,
  "error_count": 0,
  "warnings": []
}
```

---

## POST /api/exports/upload

수출 요청 데이터 업로드.

Response:

```json
{
  "uploaded_count": 4,
  "error_count": 0,
  "warnings": []
}
```

---

## POST /api/matching/run

전체 수출 요청에 대해 FIFO 자동 매칭 실행.

Request:

```json
{
  "export_date": "2025-08-16"
}
```

Response:

```json
{
  "matched_count": 2,
  "partial_matched_count": 0,
  "insufficient_stock_count": 0
}
```

---

## GET /api/inventory

재고 조회.

Query:

```text
part_number=MTG011114&origin=CN
```

Response:

```json
{
  "part_number": "MTG011114",
  "origin": "CN",
  "total_imported_qty": 2512,
  "total_exported_qty": 1600,
  "remaining_qty": 912,
  "lots": []
}
```

---

## GET /api/reports/export-allocations

수출 매칭 결과 다운로드용 데이터 조회.

---

## GET /api/reports/download.xlsx

XLSX 리포트 다운로드.

---

## 14. 샘플 시나리오

### Input

수입 재고:

```text
CN + MTG011114
2025-01-16 수입 1256개
2025-03-16 수입 1256개
```

수출 요청:

```text
2025-08-16 CN + MTG011114 800개
2025-12-16 CN + MTG011114 800개
```

### Expected Result

1차 수출:

```text
2025-01-16 lot에서 800개 차감
잔량: 456개
```

2차 수출:

```text
2025-01-16 lot에서 456개 차감
2025-03-16 lot에서 344개 차감
잔량:
- 2025-01-16 lot: 0개, used_up
- 2025-03-16 lot: 912개
```

이 로직은 녹취에서 설명된 “먼저 들어온 것부터 빼고, 부족하면 다음 수입 건에서 이어서 차감한다”는 FIFO 개념과 일치한다.

---

## 15. Codex 작업 지시문

아래 프롬프트를 Codex에 그대로 줄 수 있다.

```text
Build a web application named "처음처럼 - 원상태수출관리" with English name "As-Is".

Goal:
Create a customs refund inventory management tool for original-state re-export. Users upload import lots and export requirements as CSV/XLSX. The system validates origin, part number, HS code, 360-day eligibility, and automatically allocates export quantities to import lots using FIFO.

Tech Stack:
- Frontend: Next.js + TypeScript + Tailwind CSS
- Backend: FastAPI + Python
- Database: SQLite for MVP
- Data processing: Pandas
- Export: CSV and XLSX via openpyxl
- Tests: pytest

Core Features:
1. Upload import lot CSV/XLSX.
2. Upload export requirement CSV/XLSX.
3. Validate required columns.
4. Normalize dates and quantities.
5. Store import lots with remaining_qty.
6. Store export requirements.
7. Match export requirements to import lots by:
   - same part_number
   - same origin
   - import_accepted_date <= export_date
   - export_date - import_accepted_date <= 360 days
   - remaining_qty > 0
   - FIFO order by import_accepted_date, declaration number, line number, row number
8. Support split allocation across multiple import lots.
9. Mark lots as used_up when remaining_qty reaches 0.
10. Mark lots as expired when 360-day rule fails.
11. Show dashboard summary.
12. Show inventory search by part_number and origin.
13. Show export matching results.
14. Download allocation report as CSV/XLSX.

Data Models:
- import_lots
- export_requirements
- export_allocations

Important Business Rules:
- Never match different origins.
- Do not use expired lots.
- Do not use lots with remaining_qty = 0.
- If one lot cannot satisfy required_qty, continue with the next valid FIFO lot.
- If total valid stock is insufficient, mark export requirement as partial_matched or insufficient_stock.
- Matching result must include import declaration number, import accepted date, origin, HS code, line number, row number, matched quantity, and remaining quantity after allocation.

Implement:
- Backend API first.
- Add unit tests for FIFO, origin mismatch, 360-day expiration, split allocation, and insufficient stock.
- Then implement frontend pages:
  /upload
  /dashboard
  /inventory
  /exports
  /reports

Use the provided sample CSV/XLSX data as seed data and test fixtures.
```

---

## 16. 개발 우선순위

### Phase 1: 로직 검증

- CSV 읽기
- 수입 lot 저장
- 수출 요청 저장
- FIFO 매칭 함수
- pytest 작성

### Phase 2: 웹 UI

- 업로드 페이지
- 재고 조회 페이지
- 매칭 결과 페이지

### Phase 3: 리포트

- XLSX 다운로드
- 수출일자별 리포트
- 품번별 잔량 리포트

### Phase 4: 고도화

- HS 코드 경고
- 환급 예상액
- 만료 임박 알림
- 수동 매칭 수정
- PostgreSQL 전환

---

## 17. MVP 성공 기준

MVP는 아래가 가능하면 성공으로 본다.

```text
수입 데이터 업로드
→ 수출 요청 업로드
→ 버튼 클릭
→ FIFO 자동 매칭
→ 잔량 자동 계산
→ 수입신고번호/수리일/원산지/세번/란번호/행번호 자동 기재
→ 결과 XLSX 다운로드
```

가장 중요한 건 UI보다 **매칭 로직 정확도**다.
특히 아래 4개 테스트는 반드시 통과해야 한다.

```text
1. 같은 Part Number라도 Origin이 다르면 매칭 금지
2. 360일 초과 lot은 매칭 금지
3. 먼저 수입된 lot부터 차감
4. 부족하면 여러 lot으로 분할 매칭
```
