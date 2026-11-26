"""Response contracts shared through the generated OpenAPI schema."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MediaInfo(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: str
    duration_ms: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    codec: str | None = None
    error: str | None = None
    time_basis: str = "media_time"


class AssetOutput(BaseModel):
    id: str
    path: str
    hash: str
    fingerprint: str
    missing: int
    device: str | None = None
    info: MediaInfo
    study: dict[str, str]
    annotation: str = "not_started"


class PhaseOutput(BaseModel):
    name: str
    color: str


class LibraryOutput(BaseModel):
    assets: list[AssetOutput]
    directories: list[str]
    phases: dict[str, PhaseOutput]


class IntervalOutput(BaseModel):
    start_ms: int
    end_ms: int
    phase: Literal["P0", "P1", "P2", "P3", "P4", "unclear"] | None


class DraftOutput(BaseModel):
    asset_id: str
    source_hash: str
    duration_ms: int
    revision: int
    schema_version: int
    labels_version: str
    time_basis: str
    intervals: list[IntervalOutput]
    source_changed: bool
    saved_at: str | None = None
    annotator_id: str | None = None


class FrameOutput(BaseModel):
    file: str
    requested_ms: int
    actual_ms: float
    index: int
    is_target: bool = False
    requested_times_ms: list[int] = []
    width: int | None = None
    height: int | None = None
    device_time_ns: int | None = None


class GroupOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    asset_id: str
    source_hash: str
    created_at: str
    settings: dict[str, int]
    time_basis: str
    frames: list[FrameOutput]
    schema_version: int
    source_changed: bool = False


class JobOutput(BaseModel):
    id: str
    asset_id: str
    kind: str
    key: str
    status: Literal["queued", "running", "completed", "failed", "interrupted"]
    created_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    progress: dict[str, Any] | None = None


class FrameSetOutput(BaseModel):
    id: str
    asset_id: str
    source_hash: str
    created_at: str
    mode: str
    settings: dict[str, Any]
    time_basis: str
    schema_version: int
    frame_count: int
    sample_count: int
    source_changed: bool


class VrsExportSettings(BaseModel):
    audio: bool
    gain_db: int
    eye_gaze: bool
    hands: bool


class VrsExportOutput(BaseModel):
    source_hash: str
    created_at: str
    settings: VrsExportSettings
    time_zero_device_ns: int
    duration_ms: float
    mp4: str
    files: list[str]
    details: dict[str, Any]


class VrsFileOutput(BaseModel):
    name: str
    size: int
    mp4: str
    mp4_exists: bool
    mp4_asset_id: str | None = None
    export: VrsExportOutput | None = None
    job: JobOutput | None = None


class FramePageOutput(BaseModel):
    frames: list[FrameOutput]
    total: int
    page: int
    page_size: int
    page_count: int


class DeletionOutput(BaseModel):
    files: list[str]
    records: list[str] = []
    token: str
    annotations: int
    frame_groups: int
    vlm_runs: int = 0


class AnnotationExportItem(BaseModel):
    asset_id: str
    video_id: str
    saved_at: str | None
    source_status: Literal["current", "changed", "missing"]
    segment_count: int
    unlabeled_count: int


class AnnotationExportSummary(BaseModel):
    recording_count: int
    segment_count: int
    unlabeled_count: int
    changed_source_count: int
    missing_source_count: int


class VlmConfigOutput(BaseModel):
    configured: bool
    api_url: str
    models: list[str]


class PromptSummary(BaseModel):
    id: str
    name: str
    based_on: str | None
    created_at: str
    note: str
    hash: str


class PromptPreview(BaseModel):
    hash: str
    example: str


class PromptOutput(PromptSummary, PromptPreview):
    context: str
    phases: str
    guidance: str
    template: str
    file: str


class VlmRunSummary(BaseModel):
    id: str
    created_at: str
    settings: dict[str, Any]
    seconds: float
    counts: dict[str, int]
    status: Literal["completed", "partially_completed", "failed"] = "completed"
    error: str | None = None


class VlmRunListItem(VlmRunSummary):
    asset_id: str
    video_id: str
    prompt_id: str
    prompt_hash: str


class VlmAttemptOutput(BaseModel):
    status: Literal["valid", "invalid_output", "request_failed"]
    raw: str | None = None
    error: str | None = None


class VlmWindowOutput(BaseModel):
    start_ms: int
    end_ms: int
    target_ms: int
    actual_target_ms: float
    context_ms: list[int]
    label: str
    status: Literal["valid", "invalid_output", "request_failed"]
    reason: str | None = None
    error: str | None = None
    raw: str | None = None
    attempts: list[VlmAttemptOutput] = Field(default_factory=list)


class VlmPhaseOutput(BaseModel):
    label: str
    start_ms: int
    end_ms: int


class VlmRunOutput(VlmRunSummary):
    asset_id: str
    source_hash: str
    frame_set_id: str
    mode: str
    api_url: str
    prompt_hash: str
    prompt_id: str | None = None  # Runs before prompt versions only have the hash (v1's).
    prompt: dict[str, str] | None = None
    windows: list[VlmWindowOutput]
    phases: list[VlmPhaseOutput]


class AnnotationImportRow(BaseModel):
    index: int
    video_id: str
    source_hash: str
    segment_count: int
    unlabeled_count: int
    asset_id: str | None
    local_path: str | None
    local_revision: int
    status: Literal["new", "conflict", "identical", "no_match", "ambiguous", "invalid"]
    message: str


class AnnotationImportPreview(BaseModel):
    rows: list[AnnotationImportRow]
    counts: dict[str, int]
    token: str


class AnnotationImportResult(BaseModel):
    imported: int
    skipped: int
