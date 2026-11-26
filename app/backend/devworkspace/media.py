import bisect
import json
import subprocess
from functools import lru_cache
from pathlib import Path

from .storage import WORK, digest


def command(arguments, timeout=300):
    result = subprocess.run(arguments, capture_output=True, timeout=timeout)
    if result.returncode:
        raise ValueError(
            result.stderr.decode(errors="replace")[-1400:] or "Media operation failed."
        )
    return result.stdout


def probe(path: Path):
    value = json.loads(
        command(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ]
        )
    )
    stream = next((item for item in value["streams"] if item["codec_type"] == "video"), None)
    if not stream:
        raise ValueError("No video stream found.")
    numerator, denominator = map(int, stream.get("avg_frame_rate", "0/1").split("/"))
    return {
        "duration_ms": round(
            float(value["format"].get("duration", stream.get("duration", 0))) * 1000
        ),
        "width": stream["width"],
        "height": stream["height"],
        "fps": numerator / denominator if denominator else 0,
        "codec": stream["codec_name"],
        "status": "ready",
    }


@lru_cache(maxsize=24)
def mp4_times(path, fingerprint):
    del fingerprint
    payload = json.loads(
        command(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_frames",
                "-show_entries",
                "frame=best_effort_timestamp_time",
                "-of",
                "json",
                str(path),
            ]
        )
    )
    times = [
        float(frame["best_effort_timestamp_time"]) * 1000
        for frame in payload["frames"]
        if "best_effort_timestamp_time" in frame
    ]
    if not times:
        raise ValueError("No decoded video frame timestamps.")
    start = times[0]
    return [time - start for time in times]


def nearest_index(times, requested):
    right = bisect.bisect_left(times, requested)
    candidates = [index for index in (right - 1, right) if 0 <= index < len(times)]
    return min(candidates, key=lambda index: abs(times[index] - requested))


def export_frame(path, info, requested_ms, output, width):
    from PIL import Image

    times = mp4_times(str(path), info["fingerprint"])
    index = nearest_index(times, requested_ms)
    command(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"select=eq(n\\,{index}),scale='min({width},iw)':-2",
            "-frames:v",
            "1",
            "-q:v",
            "2",
            "-y",
            str(output),
        ]
    )
    with Image.open(output) as image:
        return {
            "actual_ms": times[index],
            "index": index,
            "width": image.width,
            "height": image.height,
        }


def make_proxy(path, asset):
    target = WORK / "previews" / asset["id"] / asset["hash"]
    target.mkdir(parents=True, exist_ok=True)
    output = target / "preview.mp4"
    if output.exists():
        return output
    temporary = target / "pending.mp4"
    command(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-movflags",
            "+faststart",
            "-y",
            str(temporary),
        ]
    )
    if digest(path) != asset["hash"]:
        temporary.unlink(missing_ok=True)
        raise ValueError("Source changed during preview preparation.")
    temporary.replace(output)
    return output
