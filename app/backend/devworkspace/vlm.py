"""Single-recording VLM run: sliding-window phase labels from the cached 0.1 s frames.

Ported from the DM2350 pilot (`run_vlm.py --mode slide`). Each target cell is labelled by one
independent request that carries the target frame plus context frames on both sides.
"""

import base64
import io
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from dotenv import load_dotenv
from PIL import Image

from . import frame_sets, prompts
from .storage import ROOT, WORK, atomic_json, read_json

# .env.local wins over the shell, so the project key is used even if one is exported.
load_dotenv(ROOT / ".env.local", override=True)
API_URL = os.environ.get("VLM_API_URL", "https://aihubmix.com/v1/chat/completions")
LABELS = prompts.LABELS
FRAME_CACHE_WIDTH = 1280  # Same cache the Frames & QC tab generates.


def api_key():
    return os.environ.get("AIHUBMIX_API_KEY", "")


def models():
    """Models offered in the UI: `VLM_MODELS` in .env.local, comma-separated, first is default.

    Keep it in line with the key's model scope in the AIHubMix console; the API does not
    report that scope.
    """
    listed = [m.strip() for m in os.environ.get("VLM_MODELS", "").split(",") if m.strip()]
    return list(dict.fromkeys(listed)) or ["qwen3-vl-plus"]


def config():
    return {"configured": bool(api_key()), "api_url": API_URL, "models": models()}


def call(model, content, retries=3):
    """Return the model's text, or raise after `retries` failed requests."""
    body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": content}],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
    )
    error = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.load(response)["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as failure:
            # Keep the provider's message, never the request headers.
            error = f"HTTP {failure.code}: {failure.read().decode(errors='replace')[:300]}"
            if failure.code in {400, 401, 403, 404}:
                break
        except Exception as failure:
            error = str(failure)
        if attempt < retries - 1:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(error)


def parse(text):
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        return None


def validate(value):
    if value and value.get("label") in LABELS:
        return None
    return "label must be one of " + ", ".join(LABELS)


def encode(path, width):
    with Image.open(path) as image:
        image.thumbnail((width, width * 4))
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, "JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode()


def targets(duration_ms, step_ms, context_ms):
    """One target per step-long cell, at the 0.1 s grid point nearest the cell centre
    (ties round up)."""
    cells, k = [], context_ms // step_ms
    for start in range(0, int(duration_ms), step_ms):
        end = min(start + step_ms, int(duration_ms))
        target = min((start + end + 100) // 200 * 100, (int(duration_ms) - 1) // 100 * 100)
        context = [target + j * step_ms for j in range(-k, k + 1)]
        cells.append(
            {
                "start_ms": start,
                "end_ms": end,
                "target_ms": target,
                "context_ms": [t for t in context if 0 <= t < duration_ms],
            }
        )
    return cells


def merge(windows):
    segments = []
    for window in windows:
        if segments and segments[-1]["label"] == window["label"]:
            segments[-1]["end_ms"] = window["end_ms"]
        else:
            segments.append(
                {
                    "label": window["label"],
                    "start_ms": window["start_ms"],
                    "end_ms": window["end_ms"],
                }
            )
    return segments


def run(asset, settings, progress=lambda *_: None):
    if not api_key():
        raise ValueError("AIHUBMIX_API_KEY is not set. Add it to .env.local and restart.")
    garment = settings["garment"] or asset["study"].get("garment")
    if garment not in {"shirt", "jacket"}:
        raise ValueError("Choose the garment, or set it in Metadata.")
    prompt = prompts.get(settings["prompt_id"])
    group = frame_sets.generate(asset, {"width": FRAME_CACHE_WIDTH}, progress)
    folder = WORK / "frames" / asset["id"] / group["id"]
    by_time = {t: frame for frame in group["frames"] for t in frame["requested_times_ms"]}
    cells = targets(group["duration_ms"], settings["step_ms"], settings["context_ms"])
    images = {}

    def image(frame):
        if frame["file"] not in images:
            images[frame["file"]] = encode(folder / frame["file"], settings["width"])
        return images[frame["file"]]

    done = 0
    lock = threading.Lock()
    started = time.time()

    def one(cell):
        nonlocal done
        frames = [by_time[t] for t in cell["context_ms"]]
        target = by_time[cell["target_ms"]]
        content = [
            {
                "type": "text",
                "text": prompts.render(
                    prompt,
                    garment=garment,
                    n=len(frames),
                    step=settings["step_ms"] / 1000,
                    target=target["actual_ms"] / 1000,
                ),
            }
        ]
        for frame in frames:
            tag = " [TARGET]" if frame is target else ""
            content += [
                {"type": "text", "text": f"t={frame['actual_ms'] / 1000:.2f}s{tag}"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/jpeg;base64," + image(frame)},
                },
            ]
        raw, value, error = None, None, None
        try:
            raw = call(settings["model"], content)
            value = parse(raw)
            error = validate(value)
            if error:
                reminder = f"Your previous answer was invalid: {error}. Return only the JSON object with an allowed label."
                raw = call(settings["model"], content + [{"type": "text", "text": reminder}])
                value = parse(raw)
                error = validate(value)
            status = "invalid_output" if error else "valid"
        except RuntimeError as failure:
            status, error = "request_failed", str(failure)
        with lock:
            done += 1
            progress(done, len(cells), "requesting")
        return {
            **cell,
            "actual_target_ms": target["actual_ms"],
            "label": value["label"] if status == "valid" else status,
            "status": status,
            "reason": (value or {}).get("reason"),
            "error": error,
            "raw": raw,
        }

    progress(0, len(cells), "requesting")
    # Encode once up front so worker threads only read the shared cache.
    for cell in cells:
        for t in cell["context_ms"]:
            image(by_time[t])
    with ThreadPoolExecutor(settings["workers"]) as pool:
        windows = list(pool.map(one, cells))
    counts = {
        status: sum(w["status"] == status for w in windows)
        for status in ("valid", "invalid_output", "request_failed")
    }
    if not counts["valid"]:
        first = next((w["error"] for w in windows if w["error"]), "No valid response.")
        raise ValueError(f"All {len(windows)} requests failed: {first}")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    result = {
        "id": run_id,
        "asset_id": asset["id"],
        "source_hash": asset["hash"],
        "frame_set_id": group["id"],
        "created_at": datetime.now(UTC).isoformat(),
        "mode": "slide",
        "api_url": API_URL,
        "settings": {**settings, "garment": garment},
        "prompt_id": prompt["id"],
        "prompt_hash": prompt["hash"],
        # The wording itself, so the run stays readable even if prompts/ changes.
        "prompt": {key: prompt[key] for key in ("name", *prompts.EDITABLE)},
        "seconds": round(time.time() - started, 1),
        "counts": counts,
        "windows": windows,
        "phases": merge(windows),
    }
    atomic_json(WORK / "vlm" / asset["id"] / f"{run_id}.json", result)
    return summary(result)


def summary(value):
    return {key: value[key] for key in ("id", "created_at", "settings", "seconds", "counts")}


def runs(asset_id):
    folder = WORK / "vlm" / asset_id
    values = [summary(read_json(path)) for path in folder.glob("*.json")]
    return sorted(values, key=lambda value: value["created_at"], reverse=True)


def get(asset_id, run_id):
    if not re.fullmatch(r"[0-9TZ]{16}-[a-f0-9]{6}", run_id):
        raise FileNotFoundError("VLM run not found.")
    path = WORK / "vlm" / asset_id / f"{run_id}.json"
    if not path.exists():
        raise FileNotFoundError("VLM run not found.")
    return read_json(path)
