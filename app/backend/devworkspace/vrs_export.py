"""VRS → MP4: convert recordings in vrs/ into MP4s in data/, where they are annotated.

The MP4 holds the RGB video at its real DEVICE_TIME frame spacing, optionally with a mono
audio track. Eye-gaze and hand-tracking CSVs go to workspace/exports/<name>/. Every time is
relative to the first RGB frame, which is time zero of the MP4 and its annotation timeline.
"""

import csv
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

EXPORT_VERSION = 2
SIDES = ("left", "right")
LANDMARKS = 21


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


def times(provider, label, rgb0):
    from projectaria_tools.core.sensor_data import TimeDomain

    source = stream(provider, label)
    stamps = provider.get_timestamps_ns(source, TimeDomain.DEVICE_TIME)
    return source, [(index, stamp, (stamp - rgb0) / 1e6) for index, stamp in enumerate(stamps)]


def gaze_csv(provider, rgb0, output):
    source, rows = times(provider, "eyegaze", rgb0)
    with output.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "device_time_ns",
                "video_ms",
                "yaw_rad",
                "pitch_rad",
                "depth_m",
                "gaze_valid",
                "point_x_cpf_m",
                "point_y_cpf_m",
                "point_z_cpf_m",
                "point_valid",
                "left_blink",
                "right_blink",
            ]
        )
        for index, stamp, video_ms in rows:
            gaze = provider.get_eye_gaze_data_by_index(source, index)
            point = list(gaze.spatial_gaze_point_in_cpf)
            writer.writerow(
                [stamp, round(video_ms, 3), gaze.yaw, gaze.pitch, gaze.depth]
                + [int(gaze.combined_gaze_valid), *point, int(gaze.spatial_gaze_point_valid)]
                + [int(gaze.vergence.left_blink), int(gaze.vergence.right_blink)]
            )
    return len(rows)


def hand_csv(provider, rgb0, output):
    """One row per sample; a hand that is not tracked leaves its columns empty."""
    source, rows = times(provider, "handtracking", rgb0)
    header = ["device_time_ns", "video_ms"]
    for side in SIDES:
        header += [f"{side}_confidence"]
        for part in ["wrist", "palm", *(f"lm{n:02d}" for n in range(LANDMARKS))]:
            header += [f"{side}_{part}_{axis}_m" for axis in "xyz"]
    with output.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        for index, stamp, video_ms in rows:
            pose = provider.get_hand_pose_data_by_index(source, index)
            row = [stamp, round(video_ms, 3)]
            for side in SIDES:
                hand = getattr(pose, f"{side}_hand")
                if hand is None:
                    row += [""] * (1 + 3 * (LANDMARKS + 2))
                    continue
                points = [hand.get_wrist_position_device(), hand.get_palm_position_device()]
                points += list(hand.landmark_positions_device)
                row += [hand.confidence] + [float(v) for point in points for v in point]
            writer.writerow(row)
    return len(rows)


def video(provider, rgb, stamps, folder, audio, settings, progress):
    """Encode every RGB frame with its real duration, so MP4 time = DEVICE_TIME - first frame."""
    from PIL import Image

    images = folder / "images"
    images.mkdir()
    lines = ["ffconcat version 1.0"]
    for index, stamp in enumerate(stamps):
        image, _ = provider.get_image_data_by_index(rgb, index)
        frame = images / f"{index:08d}.jpg"
        Image.fromarray(image.to_numpy_array()).save(frame, quality=95)
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
        filters = f"highpass=f=80,volume={settings['gain_db']}dB,alimiter=limit=0.89:level=disabled"
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
    return output


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
        details, files, wav = {}, [], None
        if settings["audio"]:
            progress(0, 0, "audio")
            wav = temporary / "audio.wav"
            details["audio"] = audio_wav(provider, rgb0, duration_ms, wav)
            details["audio"]["gain_db"] = settings["gain_db"]
        output = video(provider, rgb, stamps, temporary, wav, settings, progress)
        if wav:
            wav.unlink()
        if settings["eye_gaze"]:
            progress(0, 0, "eye_gaze")
            details["eye_gaze_rows"] = gaze_csv(provider, rgb0, temporary / "eye_gaze.csv")
            files.append("eye_gaze.csv")
        if settings["hands"]:
            progress(0, 0, "hands")
            details["hand_rows"] = hand_csv(provider, rgb0, temporary / "hand_tracking.csv")
            files.append("hand_tracking.csv")
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
            "files": files,
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


def file_path(name, filename):
    if "/" in name or "\\" in name or not name.lower().endswith(".vrs"):
        raise FileNotFoundError("Export not found.")
    folder = export_folder(name)
    if not (folder / "manifest.json").exists():
        raise FileNotFoundError("Export not found.")
    if filename not in read_json(folder / "manifest.json")["files"]:
        raise FileNotFoundError("Export file not found.")
    return folder / filename
