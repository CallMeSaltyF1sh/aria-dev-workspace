import os
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from . import media, services
from .responses import (
    AssetOutput,
    DeletionOutput,
    DraftOutput,
    GroupOutput,
    JobOutput,
    LibraryOutput,
)
from .storage import DATA, LOCK, ROOT, WORK, asset_row, assets, digest, engine, jobs, source_path


@asynccontextmanager
async def lifespan(_):
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    with engine.begin() as connection:
        connection.execute(
            update(jobs)
            .where(jobs.c.status.in_(["queued", "running"]))
            .values(status="interrupted", error="The service restarted. Retry this operation.")
        )
    yield


app = FastAPI(title="Dev Workspace", lifespan=lifespan)


@app.middleware("http")
async def local_only(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin not in {
        None,
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    }:
        return JSONResponse({"detail": "Origin not allowed."}, status_code=403)
    return await call_next(request)


@app.exception_handler(ValueError)
async def invalid(_, error):
    return JSONResponse({"detail": str(error)}, status_code=400)


@app.exception_handler(FileNotFoundError)
async def missing(_, error):
    return JSONResponse({"detail": str(error)}, status_code=404)


@app.exception_handler(RuntimeError)
async def conflict(_, error):
    return JSONResponse({"detail": str(error)}, status_code=409)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
    }


@app.get("/api/library", response_model=LibraryOutput)
def library():
    return {
        "assets": services.list_assets(),
        "directories": services.list_directories(),
        "phases": services.PHASES,
    }


@app.post("/api/scan", response_model=LibraryOutput)
def scan():
    services.scan()
    return library()


class DirectoryInput(BaseModel):
    path: str
    new_name: str | None = None


@app.post("/api/directories", response_model=LibraryOutput)
def directory_create(body: DirectoryInput):
    with LOCK:
        path = source_path(body.path)
        if path == DATA:
            raise ValueError("Choose a child folder.")
        if path.exists():
            raise ValueError("Folder already exists.")
        path.mkdir(parents=True)
    return library()


@app.patch("/api/directories", response_model=LibraryOutput)
def directory_rename(body: DirectoryInput):
    with LOCK:
        old = source_path(body.path, exists=True)
        if old == DATA or not body.new_name or "/" in body.new_name or "\\" in body.new_name:
            raise ValueError("Choose a child folder and a valid name.")
        new = source_path((old.parent.relative_to(DATA) / body.new_name).as_posix())
        if new.exists():
            raise ValueError("A file or folder with this name already exists.")
        services.ensure_idle(
            [
                row["id"]
                for row in services.list_assets()
                if source_path(row["path"]).is_relative_to(old)
            ]
        )
        old.rename(new)
        services.scan()
    return library()


@app.post("/api/import", response_model=LibraryOutput)
def import_media(
    file: UploadFile = File(),
    directory: str = Form(""),
    name: str = Form(""),
    allow_duplicate: bool = Form(False),
):
    filename = name or file.filename
    if not filename or Path(filename).name != filename or "\\" in filename:
        raise ValueError("Invalid file name.")
    if Path(filename).suffix.lower() not in {".mp4", ".vrs"}:
        raise ValueError("Choose an MP4 or VRS recording.")
    with LOCK:
        folder = source_path(directory, exists=True)
        destination = source_path((folder.relative_to(DATA) / filename).as_posix())
        if destination.exists():
            raise RuntimeError("A file with this name already exists. Skip it or enter a new name.")
        temporary = folder / f".{uuid.uuid4()}.pending"
        try:
            with temporary.open("xb") as output:
                shutil.copyfileobj(file.file, output, 1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            if destination.exists():
                raise RuntimeError("Destination appeared during import.")
            file_hash = digest(temporary)
            if not allow_duplicate and any(
                row["hash"] == file_hash and not row["missing"] for row in services.list_assets()
            ):
                raise RuntimeError(
                    "Identical content already exists. Enable Keep duplicate content to import this copy."
                )
            temporary.rename(destination)
            services.scan()
        finally:
            temporary.unlink(missing_ok=True)
    return library()


class DeleteInput(BaseModel):
    ids: list[str] = []
    directory: str | None = None
    token: str | None = None


@app.post("/api/deletion-preview", response_model=DeletionOutput)
def deletion_preview(body: DeleteInput):
    return services.deletion_preview(body.ids, body.directory)


@app.post("/api/delete", response_model=LibraryOutput)
def delete(body: DeleteInput):
    if not body.token:
        raise ValueError("Review the deletion first.")
    services.delete_files(body.ids, body.directory, body.token)
    return library()


@app.get("/api/assets/{asset_id}", response_model=AssetOutput)
def asset_detail(asset_id: str):
    return asset_row(asset_id)


class StudyInput(BaseModel):
    participant: str = ""
    trial: str = ""
    garment: Literal["", "shirt", "jacket"] = ""
    condition: Literal["", "sighted", "touch-only"] = ""
    split: Literal["", "development", "test", "training"] = ""
    overlay: Literal["", "clean", "annotated"] = ""


@app.put("/api/assets/{asset_id}/study", response_model=AssetOutput)
def study(asset_id: str, body: StudyInput):
    asset_row(asset_id)
    with engine.begin() as connection:
        connection.execute(
            update(assets).where(assets.c.id == asset_id).values(study=body.model_dump())
        )
    return asset_row(asset_id)


@app.get("/api/assets/{asset_id}/media")
def recording(asset_id: str):
    asset = asset_row(asset_id)
    path = source_path(asset["path"], exists=True)
    proxy = WORK / "previews" / asset_id / asset["hash"] / "preview.mp4"
    if proxy.exists():
        path = proxy
    if path.suffix.lower() == ".vrs":
        raise ValueError("Prepare a playable preview first.")
    return FileResponse(path, media_type="video/mp4")


@app.get("/api/assets/{asset_id}/timestamps", response_model=list[float])
def timestamps(asset_id: str):
    asset = asset_row(asset_id)
    path = source_path(asset["path"], exists=True)
    if path.suffix.lower() == ".vrs":
        from projectaria_tools.core.sensor_data import TimeDomain

        provider, stream = media.vrs_provider(path)
        times = provider.get_timestamps_ns(stream, TimeDomain.DEVICE_TIME)
        return [(stamp - times[0]) / 1e6 for stamp in times]
    return media.mp4_times(str(path), asset["fingerprint"])


class Interval(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    phase: Literal["P0", "P1", "P2", "P3", "P4", "unclear"] | None


class DraftInput(BaseModel):
    revision: int = Field(ge=0)
    intervals: list[Interval]


@app.get("/api/assets/{asset_id}/annotation", response_model=DraftOutput)
def annotation(asset_id: str):
    return services.get_draft(asset_id)


@app.put("/api/assets/{asset_id}/annotation", response_model=DraftOutput)
def save_annotation(asset_id: str, body: DraftInput):
    return services.save_draft(
        asset_id, body.revision, [item.model_dump() for item in body.intervals]
    )


class FrameInput(BaseModel):
    target_ms: int = Field(ge=0)
    count: int = Field(ge=1, le=31)
    spacing_ms: int = Field(ge=1, le=60000)
    width: int = Field(default=1280, ge=64, le=3840)


@app.post("/api/assets/{asset_id}/frames", response_model=JobOutput)
def generate_frames(asset_id: str, body: FrameInput):
    return services.submit_job(asset_id, "frames", body.model_dump())


@app.post("/api/assets/{asset_id}/preview", response_model=JobOutput)
def prepare_preview(asset_id: str):
    return services.submit_job(asset_id, "preview")


@app.get("/api/assets/{asset_id}/frames", response_model=list[GroupOutput])
def frames(asset_id: str):
    return services.frame_groups(asset_id)


@app.get("/api/frame-groups", response_model=list[GroupOutput])
def all_frame_groups():
    return [
        group for asset in services.list_assets() for group in services.frame_groups(asset["id"])
    ]


@app.get("/api/assets/{asset_id}/frames/{group_id}/{filename}")
def frame_file(asset_id: str, group_id: str, filename: str):
    group = next(
        (group for group in services.frame_groups(asset_id) if group["id"] == group_id), None
    )
    if group is None or filename not in {frame["file"] for frame in group["frames"]}:
        raise FileNotFoundError("Frame not found.")
    return FileResponse(WORK / "frames" / asset_id / group_id / filename)


@app.get("/api/jobs/{job_id}", response_model=JobOutput)
def job_status(job_id: str):
    with engine.connect() as connection:
        job = connection.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
        if job is None:
            raise FileNotFoundError("Processing job not found.")
        return dict(job)


@app.get("/api/assets/{asset_id}/jobs", response_model=list[JobOutput])
def asset_jobs(asset_id: str):
    asset_row(asset_id)
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                select(jobs).where(jobs.c.asset_id == asset_id).order_by(jobs.c.created_at.desc())
            ).mappings()
        ]


@app.get("/api/openapi.json")
def schema():
    return app.openapi()


dist = ROOT / "app" / "frontend" / "dist"
if dist.exists():
    app.mount("/static", StaticFiles(directory=dist / "static"), name="static")

    @app.get("/{path:path}")
    def frontend(path: str):
        candidate = (dist / path).resolve()
        if candidate.is_relative_to(dist) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")
