"""Whole-recording, timestamp-based frame extraction and paginated cache access."""

import hashlib
import io
import json
import math
import re
import shutil
import subprocess
import tempfile
import threading
from datetime import UTC, datetime
from functools import lru_cache

from PIL import Image

from . import media
from .storage import WORK, asset_row, atomic_json, digest, read_json, source_path

EXTRACTOR_VERSION = 3


def plan(times, duration_ms, interval_ms=100):
    """Keep all request-to-source mappings, but write each decoded frame only once."""
    if not times or any(b < a for a, b in zip(times, times[1:])):
        raise ValueError("Frame timestamps must be nonempty and ordered.")
    frames, by_index = [], {}
    for requested in range(0, math.ceil(duration_ms), interval_ms):
        index = media.nearest_index(times, requested)
        if index not in by_index:
            frame = {
                "index": index,
                "actual_ms": times[index],
                "requested_ms": requested,
                "requested_times_ms": [],
                "file": f"frame_{len(frames):06d}.jpg",
            }
            by_index[index] = frame
            frames.append(frame)
        by_index[index]["requested_times_ms"].append(requested)
    return frames


def export_mp4(path, info, frames, directory, width, progress):
    """Decode once, rather than seeking from the beginning for every requested image."""
    wanted = {frame["index"]: frame for frame in frames}
    done = 0
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-an",
                "-vf",
                f"scale='min({width},iw)':-2",
                "-fps_mode",
                "passthrough",
                "-c:v",
                "mjpeg",
                "-q:v",
                "2",
                "-f",
                "image2pipe",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=errors,
        )
        timer = threading.Timer(3600, process.kill)
        timer.daemon = True
        timer.start()
        try:
            pending = bytearray()
            index = 0
            while chunk := process.stdout.read(65536):
                pending.extend(chunk)
                while (end := pending.find(b"\xff\xd9")) >= 0:
                    jpeg = bytes(pending[: end + 2])
                    del pending[: end + 2]
                    if not jpeg.startswith(b"\xff\xd8"):
                        raise ValueError("Invalid JPEG stream during extraction.")
                    if index in wanted:
                        frame = wanted[index]
                        with Image.open(io.BytesIO(jpeg)) as image:
                            frame.update(width=image.width, height=image.height)
                        (directory / frame["file"]).write_bytes(jpeg)
                        done += 1
                        progress(done, len(frames), "extracting")
                    index += 1
                if len(pending) > 64 * 1024 * 1024:
                    raise ValueError("Decoded JPEG exceeds the supported frame size.")
            if process.wait() or pending or done != len(frames):
                errors.seek(0)
                raise ValueError(
                    errors.read().decode(errors="replace")[-1400:]
                    or "Frame extraction failed or exceeded the one-hour timeout."
                )
            if index != len(media.mp4_times(str(path), info["fingerprint"])):
                raise ValueError("Decoded frames do not match the source timestamp index.")
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()


def generate(asset, settings, progress=lambda *_: None):
    path = source_path(asset["path"], exists=True)
    settings = {"mode": "full_video", "interval_ms": 100, "width": settings["width"]}
    signature = {
        **settings,
        "source_hash": asset["hash"],
        "extractor": EXTRACTOR_VERSION,
        "stream": asset["info"].get("rgb_stream", "v:0"),
        "time_basis": asset["info"].get("time_basis", "media_time"),
    }
    group_id = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:24]
    destination = WORK / "frames" / asset["id"] / group_id
    if (destination / "manifest.json").exists():
        cached = read_json(destination / "manifest.json")
        if all(
            (destination / frame["file"]).is_file()
            and (destination / frame["file"]).stat().st_size > 0
            for frame in cached["frames"]
        ):
            progress(len(cached["frames"]), len(cached["frames"]), "cached")
            return cached
        shutil.rmtree(destination)
    temporary = destination.with_name(group_id + ".pending")
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir(parents=True)
    try:
        progress(0, 0, "indexing")
        vrs = path.suffix.lower() == ".vrs"
        if vrs:
            from projectaria_tools.core.sensor_data import TimeDomain

            provider, stream = media.vrs_provider(path)
            stamps = provider.get_timestamps_ns(stream, TimeDomain.DEVICE_TIME)
            times = [(stamp - stamps[0]) / 1e6 for stamp in stamps]
        else:
            times = media.mp4_times(str(path), asset["fingerprint"])
        frames = plan(times, asset["info"]["duration_ms"])
        if not frames:
            raise ValueError("No frames could be selected from this recording.")
        progress(0, len(frames), "extracting")
        if vrs:
            for done, frame in enumerate(frames, 1):
                image_data, _ = provider.get_image_data_by_index(stream, frame["index"])
                image = Image.fromarray(image_data.to_numpy_array())
                image.thumbnail((settings["width"], settings["width"] * 4))
                image.save(temporary / frame["file"], quality=90)
                frame.update(
                    width=image.width, height=image.height, device_time_ns=stamps[frame["index"]]
                )
                progress(done, len(frames), "extracting")
        else:
            export_mp4(path, asset, frames, temporary, settings["width"], progress)
        progress(len(frames), len(frames), "validating")
        if digest(path) != asset["hash"]:
            raise ValueError("Source changed during extraction.")
        manifest = {
            "id": group_id,
            "asset_id": asset["id"],
            "source_hash": asset["hash"],
            "created_at": datetime.now(UTC).isoformat(),
            "mode": "full_video",
            "duration_ms": asset["info"]["duration_ms"],
            "settings": settings,
            "time_basis": signature["time_basis"],
            "stream": signature["stream"],
            "frames": frames,
            "sample_count": sum(len(f["requested_times_ms"]) for f in frames),
            "schema_version": 2,
            "extractor_version": EXTRACTOR_VERSION,
        }
        atomic_json(temporary / "manifest.json", manifest)
        temporary.replace(destination)
        return manifest
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def summary(value, current_hash=None):
    return {
        key: value[key]
        for key in (
            "id",
            "asset_id",
            "source_hash",
            "created_at",
            "settings",
            "time_basis",
            "schema_version",
        )
    } | {
        "mode": value.get("mode", "legacy_target"),
        "frame_count": len(value["frames"]),
        "sample_count": value.get("sample_count", len(value["frames"])),
        "source_changed": current_hash is not None and value["source_hash"] != current_hash,
    }


@lru_cache(maxsize=4)
def cached_manifest(path, mtime, size):
    del mtime, size
    value = read_json(path)
    return value, {frame["file"] for frame in value["frames"]}


def manifest(asset_id, group_id):
    asset_row(asset_id)
    if not re.fullmatch(r"[a-f0-9]{24}", group_id):
        raise FileNotFoundError("Frame set not found.")
    path = WORK / "frames" / asset_id / group_id / "manifest.json"
    stat = path.stat()
    return cached_manifest(path, stat.st_mtime_ns, stat.st_size)


def page(asset_id, group_id, page_number, page_size):
    value, _ = manifest(asset_id, group_id)
    count = len(value["frames"])
    pages = max(1, math.ceil(count / page_size))
    if page_number > pages:
        raise ValueError("Frame page is out of range.")
    start = (page_number - 1) * page_size
    return {
        "frames": value["frames"][start : start + page_size],
        "total": count,
        "page": page_number,
        "page_size": page_size,
        "page_count": pages,
    }
