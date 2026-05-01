from pydantic import BaseModel


class UploadPreviewResponse(BaseModel):
    batch_id: str
    uploaded_count: int
    error_count: int
    warnings: list[str]
    column_mapping: dict[str, str]
    new_count: int
    duplicate_count: int
    conflict_count: int


class UploadConfirmResponse(BaseModel):
    batch_id: str
    inserted_count: int
    skipped_count: int
    error_count: int


class MatchingRunResponse(BaseModel):
    matched_count: int
    partial_matched_count: int
    insufficient_stock_count: int
    allocation_count: int
