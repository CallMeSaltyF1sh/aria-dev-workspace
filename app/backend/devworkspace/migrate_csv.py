"""Explicit, reviewed migration of the original pilot annotation CSV."""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from . import services
from .storage import WORK, asset_row, atomic_json, digest


def review(csv_path: Path):
    grouped = defaultdict(list)
    with csv_path.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            grouped[row["video_id"]].append(
                {
                    "start_ms": round(float(row["start_s"]) * 1000),
                    "end_ms": round(float(row["end_s"]) * 1000),
                    "phase": row["phase"],
                }
            )
    records = []
    for name, intervals in grouped.items():
        matches = [
            row
            for row in services.list_assets()
            if Path(row["path"]).name == name and not row["missing"]
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected one matching recording for {name}; found {len(matches)}.")
        asset = matches[0]
        draft = services.get_draft(asset["id"])
        original_end = intervals[-1]["end_ms"]
        duration = draft["duration_ms"]
        if intervals[-1]["start_ms"] >= duration:
            raise ValueError(f"Final interval is outside the recording: {name}")
        intervals[-1]["end_ms"] = duration
        records.append(
            {
                "asset_id": asset["id"],
                "path": asset["path"],
                "source_hash": asset["hash"],
                "revision": draft["revision"],
                "original_end_ms": original_end,
                "proposed_end_ms": duration,
                "change_ms": duration - original_end,
                "intervals": intervals,
            }
        )
    return {"source_csv": str(csv_path.resolve()), "csv_hash": digest(csv_path), "records": records}


def review_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def apply_review(value, approved_hash):
    if review_hash(value) != approved_hash:
        raise ValueError("Review checksum differs from the approved preview.")
    if digest(Path(value["source_csv"])) != value["csv_hash"]:
        raise ValueError("Original CSV changed after review.")
    for record in value["records"]:
        if asset_row(record["asset_id"])["hash"] != record["source_hash"]:
            raise ValueError("Recording changed after review.")
        if services.get_draft(record["asset_id"])["revision"] != record["revision"]:
            raise ValueError("Draft changed after review; generate a new preview.")
    for record in value["records"]:
        services.save_draft(record["asset_id"], record["revision"], record["intervals"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument(
        "--preview", type=Path, default=WORK / "migrations" / "pilot-csv-review.json"
    )
    parser.add_argument("--apply-approved", metavar="SHA256")
    args = parser.parse_args()
    if args.apply_approved:
        value = json.loads(args.preview.read_text())
        apply_review(value, args.apply_approved)
        print("Reviewed annotations saved. Original CSV preserved.")
        return
    value = review(args.csv)
    atomic_json(args.preview, value)
    for record in value["records"]:
        print(
            f"{record['path']}: {len(record['intervals'])} intervals; "
            f"end {record['original_end_ms']} -> {record['proposed_end_ms']} ms "
            f"({record['change_ms']:+} ms)"
        )
    print(f"Preview: {args.preview}")
    print(f"Review checksum: {review_hash(value)}")
    print("No annotations written. Apply only after the proposed changes are approved.")


if __name__ == "__main__":
    main()
