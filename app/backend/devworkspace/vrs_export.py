"""VRS → MP4: convert recordings in vrs/ into MP4s in data/, where they are annotated.

The MP4 holds the RGB video at its real DEVICE_TIME frame spacing, optionally scaled down,
with an optional mono audio track and optional eye-gaze and hand-tracking overlays drawn
onto the frames. MP4 time zero is the first RGB frame. The settings and source identity are
recorded in workspace/exports/<name>/manifest.json.
"""

import json
import os
import shutil
import time
import uuid
import wave
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import insert, select, update

from . import media, services
from .storage import DATA, LOCK, VRS, WORK, atomic_json, digest, engine, jobs, read_json

EXPORT_VERSION = 3
SIDES = ("left", "right")
# Fixed boost for the very quiet Aria microphones, followed by a limiter.
GAIN_DB = 30
# A tracking sample further than this from a video frame is not drawn on it.
MATCH_NS = 50_000_000
GAZE_COLOR = (239, 68, 68)
HAND_COLORS = {"left": (34, 197, 94), "right": (59, 130, 246)}
# Aria hand landmarks: 0–4 fingertips (thumb..pinky), 5 wrist, 6–7 thumb intermediate/distal,
# 8–19 proximal/intermediate/distal joints of index..pinky, 20 palm centre.
BONES = [
    (5, 6), (6, 7), (7, 0),
    (5, 8), (8, 9), (9, 10), (10, 1),
    (5, 11), (11, 12), (12, 13), (13, 2),
    (5, 14), (14, 15), (15, 16), (16, 3),
    (5, 17), (17, 18), (18, 19), (19, 4),
    (8, 11), (11, 14), (14, 17),
]  # fmt: skip


def vrs_provider(path):
    from projectaria_tools.core import data_provider

    provider = data_provider.create_vrs_data_provider(str(path))
    if provider is None:
        raise ValueError("VRS could not be opened.")
    streams = [
        stream
        for stream in provider.get_all_streams()
        if provider.check_stream_is_active(stream)
        and provider.get_label_from_stream_id(stream).startswith("camera-rgb")
    ]
    if not streams:
        raise ValueError("RGB unavailable in this VRS.")
    return provider, streams[0]


def vrs_path(name):
    if "/" in name or "\\" in name or name.startswith(".") or not name.lower().endswith(".vrs"):
        raise ValueError("Choose a .vrs file directly inside vrs/.")
    path = VRS / name
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError("VRS file not found in vrs/. Rescan the list.")
    return path


def mp4_name(name):
    return name[: -len(".vrs")] + ".mp4"


def export_folder(name):
    return WORK / "exports" / name[: -len(".vrs")]


def stream(provider, label):
    value = provider.get_stream_id_from_label(label)
    if value is None or not provider.get_num_data(value):
        raise ValueError(f"This VRS has no {label} data.")
    return value


def audio_wav(provider, rgb0, duration_ms, output):
    """Mix all microphone channels to mono and place each sample at its capture time."""
    mic = stream(provider, "mic")
    config = provider.get_audio_configuration(mic)
    rate, channels = config.sample_rate, config.num_channels
    mono = np.zeros(round(duration_ms / 1000 * rate), dtype=np.float64)
    for index in range(provider.get_num_data(mic)):
        data, record = provider.get_audio_data_by_index(mic, index)
        stamps = np.asarray(record.capture_timestamps_ns, dtype=np.int64)
        samples = np.asarray(data.data, dtype=np.float64).reshape(len(stamps), channels)
        positions = np.rint((stamps - rgb0) / 1e9 * rate).astype(np.int64)
        keep = (positions >= 0) & (positions < len(mono))
        mono[positions[keep]] = samples[keep].mean(axis=1)
    with wave.open(str(output), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(np.clip(mono, -32768, 32767).astype("<i2").tobytes())
    return {"sample_rate": rate, "source_channels": channels}


def projector(provider):
    """Project device-frame or CPF-frame points (metres) to full-size RGB pixels."""
    calibration = provider.get_device_calibration()
    if calibration is None:
        raise ValueError("This VRS has no calibration, so overlays cannot be drawn.")
    camera = calibration.get_camera_calib("camera-rgb")
    camera_from_device = camera.get_transform_device_camera().inverse().to_matrix()
    device_from_cpf = calibration.get_transform_device_cpf().to_matrix()

    def project(points, from_cpf=False):
        points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        if from_cpf:
            points = points @ device_from_cpf[:3, :3].T + device_from_cpf[:3, 3]
        points = points @ camera_from_device[:3, :3].T + camera_from_device[:3, 3]
        pixels = [camera.project(point) for point in points]
        return [None if pixel is None else (float(pixel[0]), float(pixel[1])) for pixel in pixels]

    return project


def samples(provider, label, read):
    """DEVICE_TIME stamps and a reader for one tracking stream."""
    from projectaria_tools.core.sensor_data import TimeDomain

    source = stream(provider, label)
    stamps = provider.get_timestamps_ns(source, TimeDomain.DEVICE_TIME)
    return stamps, lambda index: read(source, index)


def nearest(stamps, stamp):
    index = media.nearest_index(stamps, stamp)
    return index if abs(stamps[index] - stamp) <= MATCH_NS else None


def overlays(provider, settings):
    """Return draw(image, stamp, scale) for the requested overlays, or None."""
    from PIL import ImageDraw

    if not settings["eye_gaze"] and not settings["hands"]:
        return None
    project = projector(provider)
    gaze = hands = None
    if settings["eye_gaze"]:
        gaze = samples(provider, "eyegaze", provider.get_eye_gaze_data_by_index)
    if settings["hands"]:
        hands = samples(provider, "handtracking", provider.get_hand_pose_data_by_index)

    def draw(image, stamp, scale):
        pen = ImageDraw.Draw(image)
        line = max(2, round(image.width / 500))
        if hands and (index := nearest(hands[0], stamp)) is not None:
            pose = hands[1](index)
            for side in SIDES:
                hand = getattr(pose, f"{side}_hand")
                if hand is None:
                    continue
                points = project(hand.landmark_positions_device)
                points = [None if p is None else (p[0] * scale, p[1] * scale) for p in points]
                color = HAND_COLORS[side]
                for a, b in BONES:
                    if points[a] and points[b]:
                        pen.line([points[a], points[b]], fill=color, width=line)
                for point in filter(None, points):
                    r = line * 1.5
                    pen.ellipse(
                        [point[0] - r, point[1] - r, point[0] + r, point[1] + r], fill=color
                    )
        if gaze and (index := nearest(gaze[0], stamp)) is not None:
            value = gaze[1](index)
            if value.combined_gaze_valid and value.spatial_gaze_point_valid:
                [point] = project(value.spatial_gaze_point_in_cpf, from_cpf=True)
                if point:
                    x, y, r = point[0] * scale, point[1] * scale, image.width / 40
                    pen.ellipse([x - r, y - r, x + r, y + r], outline=GAZE_COLOR, width=line * 2)
                    pen.ellipse([x - line, y - line, x + line, y + line], fill=GAZE_COLOR)

    return draw


def video(provider, rgb, stamps, folder, audio, settings, progress):
    """Encode every RGB frame with its real duration, so MP4 time = DEVICE_TIME - first frame."""
    from PIL import Image

    draw = overlays(provider, settings)
    images = folder / "images"
    images.mkdir()
    lines = ["ffconcat version 1.0"]
    size = None
    for index, stamp in enumerate(stamps):
        image, _ = provider.get_image_data_by_index(rgb, index)
        image = Image.fromarray(image.to_numpy_array()).convert("RGB")
        scale = 1.0
        if settings["width"] and settings["width"] < image.width:
            scale = settings["width"] / image.width
            # Even dimensions for yuv420p.
            height = round(image.height * scale / 2) * 2
            image = image.resize((settings["width"], height), Image.LANCZOS)
        size = image.size
        if draw:
            draw(image, stamp, scale)
        frame = images / f"{index:08d}.jpg"
        image.save(frame, quality=95)
        lines += [f"file '{frame.name}'", "option framerate 1000000"]
        if index + 1 < len(stamps):
            lines.append(f"duration {(stamps[index + 1] - stamp) / 1e9:.9f}")
        progress(index + 1, len(stamps), "frames")
    (images / "frames.txt").write_text("\n".join(lines))
    progress(0, 0, "encoding")
    output = folder / "video.mp4"
    arguments = ["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0"]
    arguments += ["-i", str(images / "frames.txt")]
    if audio:
        filters = f"highpass=f=80,volume={GAIN_DB}dB,alimiter=limit=0.89:level=disabled"
        arguments += ["-i", str(audio), "-map", "0:v", "-map", "1:a", "-af", filters]
        arguments += ["-c:a", "aac", "-b:a", "192k"]
    arguments += ["-fps_mode", "passthrough", "-video_track_timescale", "1000000"]
    arguments += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    media.command(arguments + ["-y", str(output)], timeout=3600)
    shutil.rmtree(images)
    decoded = media.mp4_times(str(output), str(output.stat().st_mtime_ns))
    expected = [(stamp - stamps[0]) / 1e6 for stamp in stamps]
    if len(decoded) != len(expected) or any(abs(a - b) > 1 for a, b in zip(decoded, expected)):
        raise ValueError("MP4 timing differs from DEVICE_TIME; nothing was saved.")
    return output, size


def convert(name, settings, progress=lambda *_: None):
    from projectaria_tools.core.sensor_data import TimeDomain

    path = vrs_path(name)
    target = DATA / mp4_name(name)
    source_hash = digest(path)
    temporary = WORK / "exports" / f".{uuid.uuid4()}.pending"
    temporary.mkdir(parents=True)
    try:
        provider, rgb = vrs_provider(path)
        stamps = provider.get_timestamps_ns(rgb, TimeDomain.DEVICE_TIME)
        if len(stamps) < 2:
            raise ValueError("The RGB stream needs at least two frames.")
        rgb0, duration_ms = stamps[0], (stamps[-1] - stamps[0]) / 1e6
        details, wav = {}, None
        if settings["audio"]:
            progress(0, 0, "audio")
            wav = temporary / "audio.wav"
            details["audio"] = audio_wav(provider, rgb0, duration_ms, wav)
            details["audio"]["gain_db"] = GAIN_DB
        output, size = video(provider, rgb, stamps, temporary, wav, settings, progress)
        details["width"], details["height"] = size
        if wav:
            wav.unlink()
        progress(0, 0, "validating")
        if digest(path) != source_hash:
            raise ValueError("The VRS changed during conversion; nothing was saved.")
        manifest = {
            "source": name,
            "source_hash": source_hash,
            "created_at": datetime.now(UTC).isoformat(),
            "settings": settings,
            "time_basis": "DEVICE_TIME",
            "time_zero_device_ns": rgb0,
            "duration_ms": duration_ms,
            "mp4": target.name,
            "details": details,
            "export_version": EXPORT_VERSION,
        }
        atomic_json(temporary / "manifest.json", manifest)
        with LOCK:
            if target.exists():
                raise RuntimeError(f"data/{target.name} appeared during conversion.")
            os.replace(output, target)
            destination = export_folder(name)
            shutil.rmtree(destination, ignore_errors=True)
            temporary.replace(destination)
        services.scan()
        return manifest
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def key(name):
    return "vrs:" + name


def submit(name, settings):
    vrs_path(name)
    with LOCK, engine.begin() as connection:
        if (DATA / mp4_name(name)).exists():
            raise RuntimeError(
                f"data/{mp4_name(name)} already exists. Delete or rename it in Data Library "
                "to convert again."
            )
        active = (
            connection.execute(
                select(jobs).where(
                    jobs.c.asset_id == key(name), jobs.c.status.in_(["queued", "running"])
                )
            )
            .mappings()
            .first()
        )
        if active:
            return dict(active)
        job = {
            "id": str(uuid.uuid4()),
            "asset_id": key(name),
            "kind": "vrs_convert",
            "key": json.dumps([name, settings], sort_keys=True),
            "status": "queued",
            "created_at": services.now(),
        }
        connection.execute(insert(jobs).values(**job))

    def save(**values):
        with engine.begin() as connection:
            connection.execute(update(jobs).where(jobs.c.id == job["id"]).values(**values))

    last = [0.0, None]

    def progress(completed, total, stage):
        clock = time.monotonic()
        if stage != last[1] or clock - last[0] >= 0.25 or completed == total:
            save(progress={"completed": completed, "total": total, "stage": stage})
            last[:] = [clock, stage]

    def work():
        try:
            save(status="running")
            save(status="completed", result=convert(name, settings, progress))
        except Exception as error:
            save(status="failed", error=str(error))

    services.POOL.submit(work)
    return job


def listing():
    by_path = {a["path"]: a for a in services.list_assets() if not a["missing"]}
    with engine.connect() as connection:
        latest = {}
        for row in connection.execute(
            select(jobs).where(jobs.c.kind == "vrs_convert").order_by(jobs.c.created_at)
        ).mappings():
            latest[row["asset_id"]] = dict(row)
    found = []
    for path in sorted(VRS.iterdir()):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".vrs":
            continue
        if path.name.startswith("."):
            continue
        mp4 = mp4_name(path.name)
        manifest = export_folder(path.name) / "manifest.json"
        found.append(
            {
                "name": path.name,
                "size": path.stat().st_size,
                "mp4": mp4,
                "mp4_exists": (DATA / mp4).exists(),
                "mp4_asset_id": by_path.get(mp4, {}).get("id"),
                "export": read_json(manifest) if manifest.exists() else None,
                "job": latest.get(key(path.name)),
            }
        )
    return found
