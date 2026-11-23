import bisect
import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from .storage import WORK


def command(arguments):
    result = subprocess.run(arguments, capture_output=True, timeout=300)
    if result.returncode:
        raise ValueError(result.stderr.decode(errors="replace")[-1400:] or "Media operation failed.")
    return result.stdout


def probe(path: Path):
    value = json.loads(command([
        "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path),
    ]))
    stream = next((item for item in value["streams"] if item["codec_type"] == "video"), None)
    if not stream:
        raise ValueError("No video stream found.")
    numerator, denominator = map(int, stream.get("avg_frame_rate", "0/1").split("/"))
    return {
        "duration_ms": round(float(value["format"].get("duration", stream.get("duration", 0))) * 1000),
        "width": stream["width"], "height": stream["height"],
        "fps": numerator / denominator if denominator else 0,
        "codec": stream["codec_name"], "status": "ready",
    }


def vrs_provider(path):
    from projectaria_tools.core import data_provider
    provider = data_provider.create_vrs_data_provider(str(path))
    if provider is None:
        raise ValueError("VRS could not be opened.")
    streams = [stream for stream in provider.get_all_streams()
               if provider.check_stream_is_active(stream)
               and provider.get_label_from_stream_id(stream).startswith("camera-rgb")]
    if not streams:
        raise ValueError("RGB unavailable in this VRS.")
    return provider, streams[0]


def inspect_vrs(path):
    from projectaria_tools.core.sensor_data import TimeDomain
    provider, stream = vrs_provider(path)
    times = provider.get_timestamps_ns(stream, TimeDomain.DEVICE_TIME)
    if not times:
        raise ValueError("RGB stream is empty.")
    return {
        "duration_ms": (times[-1] - times[0]) / 1e6,
        "status": "needs_preview", "time_basis": "DEVICE_TIME", "rgb_stream": str(stream),
        "device_start_ns": times[0], "frame_count": len(times),
    }


@lru_cache(maxsize=24)
def mp4_times(path, fingerprint):
    del fingerprint
    payload = json.loads(command([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(path),
    ]))
    times = [round(float(frame["best_effort_timestamp_time"]) * 1000)
             for frame in payload["frames"] if "best_effort_timestamp_time" in frame]
    if not times:
        raise ValueError("No decoded video frame timestamps.")
    start = times[0]
    return [time - start for time in times]


def nearest_index(times, requested):
    right = bisect.bisect_left(times, requested)
    candidates = [index for index in (right - 1, right) if 0 <= index < len(times)]
    return min(candidates, key=lambda index: abs(times[index] - requested))


def export_frame(path, info, requested_ms, output, width):
    if path.suffix.lower() == ".vrs":
        from PIL import Image
        from projectaria_tools.core.sensor_data import TimeDomain
        provider, stream = vrs_provider(path)
        times = provider.get_timestamps_ns(stream, TimeDomain.DEVICE_TIME)
        relative = [(time - times[0]) / 1e6 for time in times]
        index = nearest_index(relative, requested_ms)
        image_data, _ = provider.get_image_data_by_index(stream, index)
        image = Image.fromarray(image_data.to_numpy_array())
        image.thumbnail((width, width * 4))
        image.save(output, quality=90)
        return {"actual_ms": relative[index], "device_time_ns": times[index],
                "index": index, "width": image.width, "height": image.height}
    times = mp4_times(str(path), info["fingerprint"])
    index = nearest_index(times, requested_ms)
    command([
        "ffmpeg", "-v", "error", "-i", str(path), "-vf",
        f"select=eq(n\\,{index}),scale='min({width},iw)':-2",
        "-frames:v", "1", "-q:v", "2", "-y", str(output),
    ])
    return {"actual_ms": times[index], "index": index}


def make_proxy(path, asset):
    target = WORK / "previews" / asset["id"] / asset["hash"]
    target.mkdir(parents=True, exist_ok=True)
    output = target / "preview.mp4"
    if output.exists():
        return output
    temporary = target / "pending.mp4"
    if path.suffix.lower() == ".vrs":
        from PIL import Image
        from projectaria_tools.core.sensor_data import TimeDomain
        from .storage import atomic_json
        provider, stream = vrs_provider(path)
        times = provider.get_timestamps_ns(stream, TimeDomain.DEVICE_TIME)
        directory = target / "images"
        directory.mkdir(exist_ok=True)
        try:
            lines = ["ffconcat version 1.0"]
            for index, stamp in enumerate(times):
                image, _ = provider.get_image_data_by_index(stream, index)
                frame = directory / f"{index:08d}.jpg"
                Image.fromarray(image.to_numpy_array()).save(frame)
                lines.append(f"file '{frame.as_posix()}'")
                if index + 1 < len(times):
                    lines.append(f"duration {(times[index + 1] - stamp) / 1e9:.9f}")
            concat = directory / "frames.txt"
            concat.write_text("\n".join(lines))
            command(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
                     "-fps_mode", "vfr", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                     "-movflags", "+faststart", "-y", str(temporary)])
            atomic_json(target / "time_mapping.json", {
                "time_basis": "DEVICE_TIME", "device_start_ns": times[0],
                "frames": [{"media_ms": (stamp - times[0]) / 1e6, "device_ns": stamp}
                           for stamp in times],
            })
        finally:
            shutil.rmtree(directory)
    else:
        command(["ffmpeg", "-v", "error", "-i", str(path), "-c:v", "libx264",
                 "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", "-y", str(temporary)])
    temporary.replace(output)
    return output
