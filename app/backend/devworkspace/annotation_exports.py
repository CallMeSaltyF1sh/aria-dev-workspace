"""Portable, saved-only annotation exports without media or study metadata."""

import csv
import io
import json
from datetime import UTC, datetime

from . import services
from .storage import LOCK, asset_row, draft_path, read_json, source_path


def build(asset_ids=None):
    with LOCK:
        assets = (
            [asset_row(i) for i in dict.fromkeys(asset_ids)]
            if asset_ids
            else services.list_assets()
        )
        records = []
        for asset in assets:
            path = draft_path(asset["id"])
            if not path.exists():
                continue
            draft = read_json(path)
            intervals = draft["intervals"]
            if not draft["revision"] or not any(
                item["phase"] in services.PHASES for item in intervals
            ):
                continue
            source = source_path(asset["path"])
            status = "current"
            if not source.is_file():
                status = "missing"
            else:
                stat = source.stat()
                if (
                    draft["source_hash"] != asset["hash"]
                    or f"{stat.st_size}:{stat.st_mtime_ns}" != asset["fingerprint"]
                ):
                    status = "changed"
            records.append(
                {
                    "video_id": asset["path"],
                    "asset_id": asset["id"],
                    "source_hash": draft["source_hash"],
                    "duration_ms": draft["duration_ms"],
                    "time_basis": draft["time_basis"],
                    "annotation_revision": draft["revision"],
                    "annotation_schema_version": draft["schema_version"],
                    "labels_version": draft["labels_version"],
                    "saved_at": draft.get("saved_at"),
                    "annotator_id": draft.get("annotator_id", "local"),
                    "source_status": status,
                    "intervals": intervals,
                }
            )
        records.sort(key=lambda record: record["video_id"])
        counts = {
            "recording_count": len(records),
            "segment_count": sum(len(r["intervals"]) for r in records),
            "unlabeled_count": sum(i["phase"] is None for r in records for i in r["intervals"]),
            "changed_source_count": sum(r["source_status"] == "changed" for r in records),
            "missing_source_count": sum(r["source_status"] == "missing" for r in records),
        }
        return {
            "schema_version": 1,
            "kind": "dressing_annotation_export",
            "exported_at": datetime.now(UTC).isoformat(),
            "interval_convention": "[start_ms,end_ms)",
            "counts": counts,
            "label_sets": {"dressing-v1": services.PHASES},
            "records": records,
        }


def render(value, format):
    if not value["records"]:
        raise ValueError("No saved annotations with labeled segments are available.")
    if format == "json":
        return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    stream = io.StringIO(newline="")
    fields = [
        "export_schema_version",
        "video_id",
        "asset_id",
        "source_hash",
        "duration_ms",
        "time_basis",
        "annotation_revision",
        "annotation_schema_version",
        "labels_version",
        "saved_at",
        "annotator_id",
        "source_status",
        "start_ms",
        "end_ms",
        "start_s",
        "end_s",
        "phase",
        "phase_name",
    ]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for record in value["records"]:
        metadata = {key: record[key] for key in fields if key in record}
        for interval in record["intervals"]:
            row = {
                **metadata,
                **interval,
                "export_schema_version": value["schema_version"],
                "start_s": f"{interval['start_ms'] / 1000:.3f}",
                "end_s": f"{interval['end_ms'] / 1000:.3f}",
                "phase_name": services.PHASES.get(interval["phase"], {}).get("name", ""),
            }
            # Prevent spreadsheet formula execution in user-controlled string cells.
            row = {
                key: "'" + val
                if isinstance(val, str) and val.startswith(("=", "+", "-", "@", "\t", "\r", "\n"))
                else val
                for key, val in row.items()
            }
            writer.writerow(row)
    return stream.getvalue().encode("utf-8-sig")
