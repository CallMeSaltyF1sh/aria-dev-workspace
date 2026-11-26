"""Import annotation exports (JSON or CSV, export schema v1) from another computer.

Records are matched to local recordings by source hash, because local asset IDs differ
per machine. A preview is computed first; applying recomputes it and refuses if anything
changed in between, so only what was reviewed is written.
"""

import csv
import hashlib
import io
import json
import uuid

from . import services
from .storage import LOCK, WORK, asset_row, atomic_bytes, atomic_json, draft_path, read_json

MAX_BYTES = 20 * 1024 * 1024
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def parse(content: bytes):
    if len(content) > MAX_BYTES:
        raise ValueError("Import file is larger than 20 MB.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Import file must be UTF-8 JSON or CSV.") from error
    if text.lstrip().startswith("{"):
        return parse_json(text)
    return parse_csv(text)


def parse_json(text):
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON: {error}") from error
    if (
        not isinstance(value, dict)
        or value.get("kind") != "dressing_annotation_export"
        or value.get("schema_version") != 1
    ):
        raise ValueError("Not an annotation export (expected export schema v1).")
    try:
        return [
            {
                "video_id": record["video_id"],
                "source_hash": record["source_hash"],
                "duration_ms": int(record["duration_ms"]),
                "labels_version": record["labels_version"],
                "intervals": [
                    {
                        "start_ms": int(i["start_ms"]),
                        "end_ms": int(i["end_ms"]),
                        "phase": i["phase"],
                    }
                    for i in record["intervals"]
                ],
            }
            for record in value.get("records", [])
        ]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Invalid annotation export record: {error}") from error


def unescape(cell):
    # Undo the export's spreadsheet guard: "'=x" was written for "=x".
    if cell.startswith("'") and cell[1:].startswith(FORMULA_PREFIXES):
        return cell[1:]
    return cell


def parse_csv(text):
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    required = {"export_schema_version", "video_id", "source_hash", "duration_ms", "phase"}
    if not rows or not required <= set(rows[0]):
        raise ValueError("Not an annotation export CSV (missing export columns).")
    records = {}
    try:
        for row in rows:
            if row["export_schema_version"] != "1":
                raise ValueError("Unsupported export schema version.")
            key = (unescape(row["video_id"]), row["source_hash"])
            record = records.setdefault(
                key,
                {
                    "video_id": key[0],
                    "source_hash": key[1],
                    "duration_ms": int(row["duration_ms"]),
                    "labels_version": row["labels_version"],
                    "intervals": [],
                },
            )
            record["intervals"].append(
                {
                    "start_ms": int(row["start_ms"]),
                    "end_ms": int(row["end_ms"]),
                    "phase": row["phase"] or None,
                }
            )
    except (KeyError, ValueError) as error:
        raise ValueError(f"Invalid annotation CSV: {error}") from error
    return list(records.values())


def match(record, assets):
    candidates = [a for a in assets if a["hash"] == record["source_hash"] and not a["missing"]]
    if len(candidates) > 1:
        # Identical copies: the original filename decides; otherwise it stays ambiguous.
        return [a for a in candidates if a["path"] == record["video_id"]] or candidates
    return candidates


def preview(records):
    assets = services.list_assets()
    rows, seen = [], set()
    for index, record in enumerate(records):
        row = {
            "index": index,
            "video_id": record["video_id"],
            "source_hash": record["source_hash"],
            "segment_count": len(record["intervals"]),
            "unlabeled_count": sum(i["phase"] is None for i in record["intervals"]),
            "asset_id": None,
            "local_path": None,
            "local_revision": 0,
        }
        candidates = match(record, assets)
        if not candidates:
            same_name = any(a["path"] == record["video_id"] for a in assets)
            rows.append(
                row
                | {
                    "status": "no_match",
                    "message": "A recording with this name exists, but its content differs."
                    if same_name
                    else "No local recording with this content. Add it to data/ and scan.",
                }
            )
            continue
        if len(candidates) > 1:
            rows.append(
                row
                | {
                    "status": "ambiguous",
                    "message": "Several local copies have this content; rename one to match.",
                }
            )
            continue
        asset = candidates[0]
        if asset["id"] in seen:
            rows.append(
                row
                | {
                    "status": "invalid",
                    "message": "Another record in this file is for the same recording.",
                }
            )
            continue
        seen.add(asset["id"])
        draft = services.get_draft(asset["id"])
        row |= {
            "asset_id": asset["id"],
            "local_path": asset["path"],
            "local_revision": draft["revision"],
        }
        try:
            if record["labels_version"] != draft["labels_version"]:
                raise ValueError(f"Unsupported labels version {record['labels_version']}.")
            if record["duration_ms"] != draft["duration_ms"]:
                raise ValueError("Duration differs from the local recording.")
            services.check_intervals(record["intervals"], draft["duration_ms"])
            if draft["source_changed"]:
                raise ValueError("The local annotation belongs to an older version of the video.")
        except ValueError as error:
            rows.append(row | {"status": "invalid", "message": str(error)})
            continue
        if not draft["revision"]:
            status, message = "new", "No local annotation yet."
        elif draft["intervals"] == record["intervals"]:
            status, message = "identical", "Same as the local annotation."
        else:
            status, message = "conflict", "Differs from the saved local annotation."
        rows.append(row | {"status": status, "message": message})
    token = hashlib.sha256(json.dumps([rows, records], sort_keys=True).encode()).hexdigest()
    counts = {
        status: sum(r["status"] == status for r in rows)
        for status in ("new", "conflict", "identical", "no_match", "ambiguous", "invalid")
    }
    return {"rows": rows, "counts": counts, "token": token}


def apply(content: bytes, token: str, overwrite: list[str]):
    records = parse(content)
    with LOCK:
        value = preview(records)
        if value["token"] != token:
            raise RuntimeError("Annotations changed since the preview. Review the import again.")
        selected = [
            row
            for row in value["rows"]
            if row["status"] == "new"
            or (row["status"] == "conflict" and row["asset_id"] in overwrite)
        ]
        # Check every source before the first write, including replacements not yet scanned.
        for row in selected:
            services.require_current_source(asset_row(row["asset_id"]))
        if not selected:
            return {"imported": 0, "skipped": len(value["rows"])}
        folder = WORK / "annotation_imports" / str(uuid.uuid4())
        journal = {"state": "pending", "assets": []}
        try:
            for row in selected:
                asset_id = row["asset_id"]
                path = draft_path(asset_id)
                journal["assets"].append({"asset_id": asset_id, "existed": path.exists()})
                if path.exists():
                    atomic_bytes(folder / f"{asset_id}.json", path.read_bytes())
            # The journal is durable before any draft changes.
            atomic_json(folder / "journal.json", journal)
        except Exception as error:
            raise RuntimeError(
                "Could not prepare annotation backups. No annotations changed."
            ) from error
        try:
            for row in selected:
                services.save_draft(
                    row["asset_id"], row["local_revision"], records[row["index"]]["intervals"]
                )
            for row in selected:
                services.require_current_source(asset_row(row["asset_id"]))
            atomic_json(folder / "journal.json", journal | {"state": "committed"})
        except Exception as error:
            try:
                rollback(folder, journal)
            except Exception as recovery_error:
                raise RuntimeError(
                    "Import failed and rollback is incomplete. Restart the service "
                    "to recover from workspace/annotation_imports/ backups."
                ) from recovery_error
            raise RuntimeError(
                "Import failed. All affected annotations were restored; review the import again."
            ) from error
    return {"imported": len(selected), "skipped": len(value["rows"]) - len(selected)}


def rollback(folder, journal):
    for item in journal["assets"]:
        asset_id = str(uuid.UUID(item["asset_id"]))
        path = draft_path(asset_id)
        if item["existed"]:
            atomic_bytes(path, (folder / f"{asset_id}.json").read_bytes())
        else:
            path.unlink(missing_ok=True)
    atomic_json(folder / "journal.json", journal | {"state": "rolled_back"})


def recover_pending():
    """Finish rollback after a process stopped between draft writes and commit marker."""
    with LOCK:
        for path in (WORK / "annotation_imports").glob("*/journal.json"):
            journal = read_json(path)
            if journal["state"] == "pending":
                rollback(path.parent, journal)
