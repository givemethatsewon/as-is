from __future__ import annotations

from io import BytesIO

from openpyxl import load_workbook


def test_upload_confirm_match_and_download_reports(client):
    import_csv = (
        "import_declaration_no,import_accepted_date,origin,hs_code,line_no,row_no,part_number,spec,import_qty,qty_unit\n"
        "A,2025-01-16,CN,8708309000,004,01,MTG011114,STEERING RACK,1256,PC\n"
    )
    export_csv = (
        "export_date,origin,part_number,required_qty,description,unit_price\n"
        "2025-08-16,CN,MTG011114,800,STEERING RACK,3\n"
    )

    import_preview = client.post(
        "/api/imports/preview",
        files={"file": ("imports.csv", import_csv, "text/csv")},
    )
    assert import_preview.status_code == 200
    import_batch_id = import_preview.json()["batch_id"]
    import_confirm = client.post("/api/imports/confirm", data={"batch_id": import_batch_id})
    assert import_confirm.status_code == 200
    assert import_confirm.json()["inserted_count"] == 1

    export_preview = client.post(
        "/api/exports/preview",
        files={"file": ("exports.csv", export_csv, "text/csv")},
    )
    assert export_preview.status_code == 200
    export_batch_id = export_preview.json()["batch_id"]
    export_confirm = client.post("/api/exports/confirm", data={"batch_id": export_batch_id})
    assert export_confirm.status_code == 200
    assert export_confirm.json()["inserted_count"] == 1

    matching = client.post("/api/matching/run")
    assert matching.status_code == 200
    assert matching.json()["matched_count"] == 1
    assert matching.json()["allocation_count"] == 1

    inventory = client.get("/api/inventory", params={"part_number": "MTG011114", "origin": "CN"})
    assert inventory.status_code == 200
    assert inventory.json()["remaining_qty"] == 456

    csv_response = client.get("/api/reports/export-allocations.csv")
    assert csv_response.status_code == 200
    assert "export_match_allocations.csv" in csv_response.headers["content-disposition"]
    assert "MTG011114" in csv_response.text

    xlsx_response = client.get("/api/reports/download.xlsx")
    assert xlsx_response.status_code == 200
    assert xlsx_response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert xlsx_response.content.startswith(b"PK")

    workbook = load_workbook(BytesIO(xlsx_response.content))
    assert "수입신고별 잔량" in workbook.sheetnames
    sheet = workbook["수출건별 수입근거 매칭"]
    assert sheet["A1"].value == "수출일"
    assert sheet["A1"].font.bold
    assert sheet["A1"].fill.fgColor.rgb == "000F5F50"
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == sheet.dimensions
    headers = [cell.value for cell in sheet[1]]
    match_status_column = headers.index("매칭 상태") + 1
    assert sheet.cell(row=2, column=match_status_column).value == "매칭 완료"
    assert "수출신고번호" not in headers
    assert "수출수리일" not in headers
    assert "수출 란번호" not in headers
    assert "수입 란번호" in headers
    assert "수입 행번호" in headers

    contest_response = client.get("/api/reports/contest-example.xlsx")
    assert contest_response.status_code == 200
    assert contest_response.content.startswith(b"PK")
    contest_workbook = load_workbook(BytesIO(contest_response.content))
    assert contest_workbook.sheetnames[:2] == ["수출 전 확인용 잔량표", "수출 건별 수입근거 자동기재표"]
    basis_sheet = contest_workbook["수출 건별 수입근거 자동기재표"]
    basis_headers = [cell.value for cell in basis_sheet[1]]
    assert "수입신고번호" in basis_headers
    assert "수리일" in basis_headers
    assert "란번호" in basis_headers
    assert "행번호" in basis_headers
    assert "매칭 수량" in basis_headers
    assert "매칭 후 잔량" in basis_headers
    assert basis_sheet.cell(row=2, column=basis_headers.index("수입신고번호") + 1).value == "A"


def test_import_preview_supports_column_aliases(client):
    import_csv = (
        "수입신고번호,declaration_date,원산지,HS Code,란번호,행번호,Part Number,규격,수량,수량단위\n"
        "A,2025-01-16,CN,8708309000,004,01,MTG011114,STEERING RACK,1256,PC\n"
    )

    response = client.post(
        "/api/imports/preview",
        files={"file": ("imports.csv", import_csv, "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["new_count"] == 1
    assert body["column_mapping"]["import_accepted_date"] == "declaration_date"
    assert body["column_mapping"]["import_declaration_no"] == "수입신고번호"
    assert body["column_mapping"]["part_number"] == "Part Number"


def test_import_preview_missing_canonical_column_reports_found_columns(client):
    import_csv = (
        "수입신고번호,원산지,HS Code,란번호,행번호,Part Number,규격,수량,수량단위\n"
        "A,CN,8708309000,004,01,MTG011114,STEERING RACK,1256,PC\n"
    )

    response = client.post(
        "/api/imports/preview",
        files={"file": ("imports.csv", import_csv, "text/csv")},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "import_accepted_date" in detail
    assert "Found columns" in detail
    assert "수입신고번호" in detail


def test_export_preview_allows_optional_description_and_unit_price(client):
    export_csv = (
        "export_date,origin,part_number,required_qty\n"
        "2025-08-16,CN,MTG011114,800\n"
    )

    response = client.post(
        "/api/exports/preview",
        files={"file": ("exports.csv", export_csv, "text/csv")},
    )

    assert response.status_code == 200
    assert response.json()["new_count"] == 1


def test_import_preview_page_shows_canonical_field_descriptions(client):
    import_csv = (
        "import_declaration_no,declaration_date,origin,hs_code,line_no,row_no,part_number,spec,import_qty,qty_unit\n"
        "A,2025-01-16,CN,8708309000,004,01,MTG011114,STEERING RACK,1256,PC\n"
    )

    response = client.post(
        "/upload/imports/preview",
        files={"file": ("imports.csv", import_csv, "text/csv")},
    )

    assert response.status_code == 200
    assert "import_accepted_date" in response.text
    assert "수입신고 수리일" in response.text
    assert "품번 / Part Number" in response.text


def test_upload_review_detail_delete_and_invalidate_workflow(client):
    import_csv = (
        "import_declaration_no,declaration_date,origin,hs_code,line_no,row_no,part_number,spec,import_qty,qty_unit\n"
        "A,2025-01-16,CN,8708309000,004,01,MTG011114,STEERING RACK,1256,PC\n"
    )

    preview = client.post(
        "/api/imports/preview",
        files={"file": ("imports.csv", import_csv, "text/csv")},
    )
    batch_id = preview.json()["batch_id"]

    detail = client.get(f"/upload/reviews/{batch_id}")
    assert detail.status_code == 200
    assert "행별 결과" in detail.text
    assert "컬럼 연결" in detail.text

    upload_page = client.get("/upload")
    assert "상세 보기" in upload_page.text
    assert "삭제" in upload_page.text
    assert "업로드" in upload_page.text
    assert "배치" not in upload_page.text

    delete = client.post("/upload/delete", data={"batch_id": batch_id}, follow_redirects=False)
    assert delete.status_code == 303
    assert client.get(f"/upload/reviews/{batch_id}").status_code == 404

    second_preview = client.post(
        "/api/imports/preview",
        files={"file": ("imports.csv", import_csv, "text/csv")},
    )
    confirmed_batch_id = second_preview.json()["batch_id"]
    assert client.post("/api/imports/confirm", data={"batch_id": confirmed_batch_id}).status_code == 200

    delete_confirmed = client.post("/upload/delete", data={"batch_id": confirmed_batch_id})
    assert delete_confirmed.status_code == 400
    assert "무효 처리" in delete_confirmed.text

    invalidate = client.post(
        "/upload/invalidate",
        data={"batch_id": confirmed_batch_id, "reason": "잘못 올린 수입 파일"},
        follow_redirects=True,
    )
    assert invalidate.status_code == 200
    assert "무효 처리" in invalidate.text

    detail_after_invalidate = client.get(f"/upload/reviews/{confirmed_batch_id}")
    assert "무효 처리된 파일입니다" in detail_after_invalidate.text
    assert "잘못 올린 수입 파일" in detail_after_invalidate.text


def test_invalidated_confirmed_upload_is_excluded_from_inventory_matching_and_reports(client):
    import_csv = (
        "import_declaration_no,declaration_date,origin,hs_code,line_no,row_no,part_number,spec,import_qty,qty_unit\n"
        "A,2025-01-16,CN,8708309000,004,01,MTG011114,STEERING RACK,100,PC\n"
    )
    export_csv = "export_date,origin,part_number,required_qty\n2025-08-16,CN,MTG011114,60\n"

    import_preview = client.post("/api/imports/preview", files={"file": ("imports.csv", import_csv, "text/csv")})
    import_batch_id = import_preview.json()["batch_id"]
    assert client.post("/api/imports/confirm", data={"batch_id": import_batch_id}).status_code == 200

    export_preview = client.post("/api/exports/preview", files={"file": ("exports.csv", export_csv, "text/csv")})
    export_batch_id = export_preview.json()["batch_id"]
    assert client.post("/api/exports/confirm", data={"batch_id": export_batch_id}).status_code == 200

    assert client.post("/api/matching/run").json()["allocation_count"] == 1

    invalidate = client.post(
        "/upload/invalidate",
        data={"batch_id": import_batch_id, "reason": "중복 업로드"},
        follow_redirects=True,
    )
    assert invalidate.status_code == 200

    inventory = client.get("/api/inventory", params={"part_number": "MTG011114", "origin": "CN"})
    assert inventory.json()["total_imported_qty"] == 0
    assert inventory.json()["remaining_qty"] == 0
    assert inventory.json()["lots"] == []

    allocations = client.get("/api/reports/export-allocations").json()
    assert allocations == []

    matching = client.post("/api/matching/run")
    assert matching.json()["insufficient_stock_count"] == 1


def test_invalidated_import_upload_can_be_reactivated_by_reupload(client):
    original_import_csv = (
        "import_declaration_no,declaration_date,origin,hs_code,line_no,row_no,part_number,spec,import_qty,qty_unit\n"
        "A,2025-01-16,CN,8708309000,004,01,MTG011114,STEERING RACK,100,PC\n"
    )
    corrected_import_csv = (
        "import_declaration_no,declaration_date,origin,hs_code,line_no,row_no,part_number,spec,import_qty,qty_unit\n"
        "A,2025-01-16,CN,8708309000,004,01,MTG011114,STEERING RACK CORRECTED,120,PC\n"
    )

    preview = client.post("/api/imports/preview", files={"file": ("imports.csv", original_import_csv, "text/csv")})
    original_batch_id = preview.json()["batch_id"]
    assert client.post("/api/imports/confirm", data={"batch_id": original_batch_id}).status_code == 200

    invalidate = client.post(
        "/upload/invalidate",
        data={"batch_id": original_batch_id, "reason": "수량 수정"},
        follow_redirects=True,
    )
    assert invalidate.status_code == 200

    reupload_preview = client.post(
        "/api/imports/preview",
        files={"file": ("imports.csv", corrected_import_csv, "text/csv")},
    )
    assert reupload_preview.status_code == 200
    assert reupload_preview.json()["new_count"] == 0
    assert reupload_preview.json()["reactivate_count"] == 1

    reupload_batch_id = reupload_preview.json()["batch_id"]
    reupload_confirm = client.post("/api/imports/confirm", data={"batch_id": reupload_batch_id})
    assert reupload_confirm.status_code == 200
    assert reupload_confirm.json()["inserted_count"] == 0
    assert reupload_confirm.json()["reactivated_count"] == 1

    inventory = client.get("/api/inventory", params={"part_number": "MTG011114", "origin": "CN"})
    body = inventory.json()
    assert body["total_imported_qty"] == 120
    assert body["remaining_qty"] == 120
    assert body["lots"][0]["spec"] == "STEERING RACK CORRECTED"


def test_exports_page_shows_current_matching_rules(client):
    response = client.get("/exports")

    assert response.status_code == 200
    assert "현재 매칭 기준" in response.text
    assert "품번 동일" in response.text
    assert "원산지 동일" in response.text
    assert "360일 이내" in response.text
    assert "잔량 &gt; 0" in response.text
    assert "FIFO" in response.text
    assert "HS 코드가 다르면 매칭은 진행하고 경고를 남깁니다" in response.text


def test_reports_page_uses_clear_download_copy_and_term_explanations(client):
    response = client.get("/reports")

    assert response.status_code == 200
    assert "매칭 결과와 재고 현황을 파일로 내보냅니다." in response.text
    assert "수입신고별 잔량" in response.text
    assert "수출건별 매칭 결과" in response.text
    assert "매칭 결과 CSV" in response.text
    assert "전체 리포트 XLSX" in response.text
    assert "공모전 양식 XLSX" in response.text
    assert "환급예상" in response.text
    assert "수입 재고가 없습니다" in response.text
    assert "매칭 결과가 없습니다" in response.text


def test_inventory_page_translates_status_filter_labels(client):
    response = client.get("/inventory")

    assert response.status_code == 200
    assert "조회" in response.text
    assert "사용 가능" in response.text
    assert "만료 예정" in response.text
    assert "용어 보기" in response.text
    assert "수리일" in response.text
    assert "수입신고 수리일" in response.text
