from __future__ import annotations


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
