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

