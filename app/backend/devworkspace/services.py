import hashlib
import json
import os
import shutil
import uuid
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy import insert, select, update

from . import media, frame_sets, vlm
from .storage import (
    DATA,
    LOCK,
    WORK,
    asset_row,
    assets,
    atomic_json,
    digest,
    draft_path,
    engine,
    jobs,
    read_json,
    source_path,
)

POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="media")
PHASES = {
    "P0": {"name": "No garment action", "color": "#e4e4e7"},
    "P1": {"name": "Acquire garment", "color": "#f9e5ac"},
    "P2": {"name": "Orient garment", "color": "#fbd4bc"},
    "P3": {"name": "Position garment", "color": "#c7ddff"},
    "P4": {"name": "Adjust / fasten garment", "color": "#c5eadc"},
    "unclear": {"name": "Action cannot be identified", "color": "#e6d8f7"},
}


def now():
    return datetime.now(UTC).isoformat()


def require_current_source(asset):
    path = source_path(asset["path"], exists=True)
    stat = path.stat()
    if f"{stat.st_size}:{stat.st_mtime_ns}" != asset["fingerprint"]:
        raise ValueError("Source changed on disk. Scan data/ before continuing.")
    return path


def scan():
    with LOCK, engine.begin() as connection:
        previous = [dict(row) for row in connection.execute(select(assets)).mappings()]
        paths = {row["path"]: row for row in previous}
        seen = set()
        for directory, folders, filenames in os.walk(DATA, followlinks=False):
            folders[:] = [
                name
                for name in folders
                if not (os.path.join(directory, name)).endswith(".pending")
                and not (DATA / os.path.relpath(os.path.join(directory, name), DATA)).is_symlink()
            ]
            for name in filenames:
                candidate = os.path.join(directory, name)
                if os.path.islink(candidate):
                    continue
                path = source_path(os.path.relpath(candidate, DATA))
                if path.suffix.lower() not in {".mp4", ".vrs"}:
                    continue
                relative = path.relative_to(DATA).as_posix()
                stat = path.stat()
                fingerprint = f"{stat.st_size}:{stat.st_mtime_ns}"
                device = f"{stat.st_dev}:{stat.st_ino}"
                row = paths.get(relative)
                if row is None:
                    row = next(
                        (
                            old
                            for old in previous
                            if old["device"] == device
                            and old["id"] not in seen
                            and not source_path(old["path"]).exists()
                        ),
                        None,
                    )
                if row and row["fingerprint"] == fingerprint and not row["missing"]:
                    seen.add(row["id"])
                    if row["path"] != relative:
                        connection.execute(
                            update(assets).where(assets.c.id == row["id"]).values(path=relative)
                        )
                    continue
                asset_id = row["id"] if row else str(uuid.uuid4())
                seen.add(asset_id)
                try:
                    info = (
                        media.inspect_vrs(path)
                        if path.suffix.lower() == ".vrs"
                        else media.probe(path)
                    )
                    file_hash = digest(path)
                except Exception as error:
                    info = {"status": "error", "error": str(error)}
                    file_hash = digest(path)
                values = dict(
                    path=relative,
                    fingerprint=fingerprint,
                    hash=file_hash,
                    device=device,
                    info=info,
                    missing=0,
                )
                if row:
                    connection.execute(
                        update(assets).where(assets.c.id == asset_id).values(**values)
                    )
                else:
                    connection.execute(insert(assets).values(id=asset_id, study={}, **values))
        for old in previous:
            if old["id"] not in seen:
                connection.execute(update(assets).where(assets.c.id == old["id"]).values(missing=1))
    return list_assets()


def list_assets():
    with engine.connect() as connection:
        result = [dict(row) for row in connection.execute(select(assets)).mappings()]
    for row in result:
        row["annotation"] = "not_started"
        if draft_path(row["id"]).exists():
            draft = read_json(draft_path(row["id"]))
            row["annotation"] = "source_changed" if draft["source_hash"] != row["hash"] else "saved"
        if row["missing"]:
            row["info"] = {**row["info"], "status": "missing"}
    return sorted(result, key=lambda row: row["path"])


def list_directories():
    directories = []
    for directory, folders, _ in os.walk(DATA, followlinks=False):
        folders[:] = [
            name
            for name in folders
            if not (os.path.join(directory, name)).endswith(".pending")
            and not (DATA / os.path.relpath(os.path.join(directory, name), DATA)).is_symlink()
        ]
        directories.append(
            os.path.relpath(directory, DATA).replace(".", "", 1)
            if directory == str(DATA)
            else os.path.relpath(directory, DATA)
        )
    return sorted(directories)


def ensure_idle(asset_ids):
    with engine.connect() as connection:
        active = connection.execute(
            select(jobs).where(
                jobs.c.asset_id.in_(asset_ids),
                jobs.c.status.in_(["queued", "running"]),
            )
        ).first()
        if active:
            raise ValueError("Media processing is active. Wait for it to finish before deleting.")


def deletion_preview(ids=None, directory=None):
    if directory is not None:
        path = source_path(directory, exists=True)
        if path == DATA or not path.is_dir():
            raise ValueError("Choose a child folder.")
        paths = [item for item in path.rglob("*") if item.is_file() or item.is_symlink()]
        if any(item.is_symlink() for item in path.rglob("*")):
            raise ValueError("Remove symbolic links before deleting this folder.")
        rows = [row for row in list_assets() if source_path(row["path"]).is_relative_to(path)]
    else:
        rows = [asset_row(asset_id) for asset_id in dict.fromkeys(ids or [])]
        paths = [source_path(row["path"], exists=True) for row in rows]
    ensure_idle([row["id"] for row in rows])
    files = sorted({item.relative_to(DATA).as_posix() for item in paths})
    stamps = [
        (item.relative_to(DATA).as_posix(), item.stat().st_size, item.stat().st_mtime_ns)
        for item in paths
    ]
    token = hashlib.sha256(json.dumps(sorted(stamps)).encode()).hexdigest()
    return {
        "files": files,
        "token": token,
        "annotations": sum(draft_path(row["id"]).exists() for row in rows),
        "frame_groups": sum(len(frame_groups(row["id"])) for row in rows),
    }


def delete_files(ids, directory, token):
    with LOCK:
        preview = deletion_preview(ids, directory)
        if preview["token"] != token:
            raise ValueError("Files changed since confirmation. Review the deletion again.")
        if directory is not None:
            shutil.rmtree(source_path(directory, exists=True))
        else:
            for relative in preview["files"]:
                source_path(relative, exists=True).unlink()
        return scan()


def get_draft(asset_id):
    asset = asset_row(asset_id)
    duration = round(asset["info"].get("duration_ms", 0))
    if draft_path(asset_id).exists():
        draft = read_json(draft_path(asset_id))
        return {**draft, "source_changed": draft["source_hash"] != asset["hash"]}
    return {
        "asset_id": asset_id,
        "source_hash": asset["hash"],
        "duration_ms": duration,
        "revision": 0,
        "schema_version": 1,
        "labels_version": "dressing-v1",
        "time_basis": asset["info"].get("time_basis", "media_time"),
        "intervals": [{"start_ms": 0, "end_ms": duration, "phase": None}],
        "source_changed": False,
    }


def check_intervals(intervals, duration):
    end = 0
    for index, interval in enumerate(intervals):
        start, stop, phase = interval["start_ms"], interval["end_ms"], interval["phase"]
        if start != end or stop <= start or stop > duration or phase not in [None, *PHASES]:
            raise ValueError("Intervals must cover the recording without gaps or overlaps.")
        if index < len(intervals) - 1 and stop % 100:
            raise ValueError("Editable boundaries must use 0.1-second steps.")
        if index < len(intervals) - 1 and stop - start < 100:
            raise ValueError("Segments must be at least 0.1 seconds.")
        end = stop
    if not intervals or end != duration:
        raise ValueError("Annotation must cover the complete recording.")


def save_draft(asset_id, revision, intervals):
    with LOCK:
        asset = asset_row(asset_id)
        require_current_source(asset)
        draft = get_draft(asset_id)
        if draft["source_changed"]:
            raise ValueError(
                "Source changed. Review the new recording before replacing its annotation."
            )
        if draft["revision"] != revision:
            raise RuntimeError("A newer draft was saved. Reload before editing again.")
        check_intervals(intervals, round(asset["info"].get("duration_ms", 0)))
        draft.update(
            intervals=intervals,
            revision=revision + 1,
            saved_at=now(),
            annotator_id="local",
            source_changed=False,
        )
        atomic_json(draft_path(asset_id), draft)
        return draft


def frame_groups(asset_id):
    directory = WORK / "frames" / asset_id
    result = []
    current = asset_row(asset_id)
    for path in directory.glob("*/manifest.json"):
        if path.parent.name.endswith(".pending"):
            continue
        try:
            stat = path.stat()
            cached, _ = frame_sets.cached_manifest(path, stat.st_mtime_ns, stat.st_size)
            value = dict(cached)
            value["source_changed"] = value["source_hash"] != current["hash"]
            result.append(value)
        except (ValueError, OSError):
            continue
    return sorted(result, key=lambda value: value["created_at"], reverse=True)


def create_frames(asset, settings, progress=lambda *_: None):
    return frame_sets.generate(asset, settings, progress)


def submit_job(asset_id, kind, settings=None):
    with LOCK, engine.begin() as connection:
        asset = asset_row(asset_id)
        require_current_source(asset)
        if asset["info"]["status"] == "error":
            raise ValueError(asset["info"].get("error", "Media cannot be decoded."))
        key = json.dumps([kind, asset["hash"], settings], sort_keys=True)
        active = (
            connection.execute(
                select(jobs).where(
                    jobs.c.asset_id == asset_id,
                    jobs.c.key == key,
                    jobs.c.status.in_(["queued", "running"]),
                )
            )
            .mappings()
            .first()
        )
        if active:
            return dict(active)
        job = {
            "id": str(uuid.uuid4()),
            "asset_id": asset_id,
            "kind": kind,
            "key": key,
            "status": "queued",
            "created_at": now(),
        }
        connection.execute(insert(jobs).values(**job))

    def work():
        try:
            with engine.begin() as connection:
                connection.execute(
                    update(jobs).where(jobs.c.id == job["id"]).values(status="running")
                )
            if kind in {"frames", "vlm"}:
                last_update = 0.0
                last_stage = None

                def progress(completed, total, stage):
                    nonlocal last_update, last_stage
                    clock = time.monotonic()
                    if stage != last_stage or clock - last_update >= 0.25 or completed == total:
                        with engine.begin() as connection:
                            connection.execute(
                                update(jobs)
                                .where(jobs.c.id == job["id"])
                                .values(
                                    progress={
                                        "completed": completed,
                                        "total": total,
                                        "stage": stage,
                                    }
                                )
                            )
                        last_update, last_stage = clock, stage

                if kind == "vlm":
                    result = vlm.run(asset, settings, progress)
                else:
                    result = frame_sets.summary(
                        create_frames(asset, settings, progress), asset["hash"]
                    )
            else:
                output = media.make_proxy(source_path(asset["path"], exists=True), asset)
                result = {"path": output.relative_to(WORK).as_posix()}
            with engine.begin() as connection:
                connection.execute(
                    update(jobs)
                    .where(jobs.c.id == job["id"])
                    .values(status="completed", result=result)
                )
        except Exception as error:
            with engine.begin() as connection:
                connection.execute(
                    update(jobs)
                    .where(jobs.c.id == job["id"])
                    .values(status="failed", error=str(error))
                )

    POOL.submit(work)
    return job
