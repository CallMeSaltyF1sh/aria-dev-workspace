"""Versioned VLM prompts kept as JSON files in the repository's `prompts/` folder.

A version is never edited in place: runs record which version and hash they used, so a
change is saved as a new file. Only the wording is editable. The description of the input
frames and the JSON answer format are fixed here, so every version stays parseable and
uses the same labels.
"""

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

DIR = Path(os.environ.get("PROMPTS_DIR", Path(__file__).resolve().parents[3] / "prompts"))
EDITABLE = ("context", "phases", "guidance")
LABELS = ["P0", "P1", "P2", "P3", "P4", "unclear"]

INPUT = """The clip is shown as {n} frames in time order, one every {step:g} s. Each frame is preceded
by its timestamp. The frame marked [TARGET] is at t={target:.2f} s; the other frames are
context only."""
TASK = "Classify the action at the TARGET frame into exactly one phase:"
OUTPUT = """Return only a JSON object in this format:
{{"label": "P0" | "P1" | "P2" | "P3" | "P4" | "unclear",
 "reason": "<one short sentence describing the visible action at the TARGET frame>"}}"""
EXAMPLE = {"garment": "jacket", "n": 9, "step": 0.5, "target": 12.3}


def template(value):
    """Full template with `{garment}`, `{n}`, `{step}`, `{target}` and `{phases}` holes."""
    return f"{value['context']}\n{INPUT}\n\n{TASK}\n{{phases}}\n\n{value['guidance']}\n\n{OUTPUT}"


def content_hash(value):
    return hashlib.sha256((template(value) + value["phases"]).encode()).hexdigest()[:12]


def render(value, garment, n, step, target):
    return template(value).format(
        garment=garment, n=n, step=step, target=target, phases=value["phases"]
    )


def check(value):
    for key in EDITABLE:
        text = value.get(key)
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{key.capitalize()} must not be empty.")
        allowed = "{garment}" if key != "phases" else ""
        rest = text.replace(allowed, "") if allowed else text
        if "{" in rest or "}" in rest:
            raise ValueError(
                f"{key.capitalize()} may use {{garment}} but no other braces."
                if allowed
                else "Phases may not contain braces."
            )
    missing = [label for label in LABELS if not re.search(rf"^{label}\b", value["phases"], re.M)]
    if missing:
        raise ValueError(
            "Phases must define every label at the start of a line: " + ", ".join(missing)
        )


def number(prompt_id):
    match = re.fullmatch(r"v([1-9][0-9]*)", prompt_id)
    if not match:
        raise FileNotFoundError("Prompt version not found.")
    return int(match.group(1))


def full(value):
    return value | {
        "hash": content_hash(value),
        "template": template(value),
        "example": render(value, **EXAMPLE),
        "file": f"prompts/{value['id']}.json",
    }


def get(prompt_id):
    path = DIR / f"v{number(prompt_id)}.json"
    if not path.is_file():
        raise FileNotFoundError("Prompt version not found.")
    value = json.loads(path.read_text())
    check(value)
    return full(value)


def listing():
    values = [
        get(path.stem) for path in DIR.glob("v*.json") if re.fullmatch(r"v[1-9][0-9]*", path.stem)
    ]
    values.sort(key=lambda value: number(value["id"]), reverse=True)
    return [
        {key: value[key] for key in ("id", "name", "based_on", "created_at", "note", "hash")}
        for value in values
    ]


def latest():
    values = listing()
    if not values:
        raise FileNotFoundError("No prompt versions in prompts/.")
    return values[0]["id"]


def preview(value):
    check(value)
    return {"hash": content_hash(value), "example": render(value, **EXAMPLE)}


def create(value):
    check(value)
    get(value["based_on"])
    digest = content_hash(value)
    same = next((p["id"] for p in listing() if p["hash"] == digest), None)
    if same:
        raise ValueError(f"The wording is identical to {same}; change something first.")
    prompt_id = f"v{max([number(p['id']) for p in listing()] or [0]) + 1}"
    record = {
        "id": prompt_id,
        "name": value["name"].strip(),
        "based_on": value["based_on"],
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "note": value.get("note", "").strip(),
        **{key: value[key] for key in EDITABLE},
    }
    # "x": never overwrite a version that appeared meanwhile.
    try:
        with (DIR / f"{prompt_id}.json").open("x") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError as error:
        raise RuntimeError(f"{prompt_id} was just saved by someone else; save again.") from error
    return get(prompt_id)
