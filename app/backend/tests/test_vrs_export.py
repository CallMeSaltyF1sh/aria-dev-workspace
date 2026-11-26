"""VRS → MP4 with a simulated provider; the real-recording check is done by hand."""

import csv
import json
import subprocess
import time
import wave
from types import SimpleNamespace

import numpy as np

from devworkspace import media, services, vrs_export
from devworkspace.storage import DATA, VRS, WORK

BASE = 5_000_000_000
RGB = [BASE, BASE + 100_000_000, BASE + 200_000_000, BASE + 300_000_000]
RATE, CHANNELS, BLOCK = 8000, 8, 400
# Audio starts 50 ms before the first RGB frame; the export must trim that part.
AUDIO_START = BASE - 50_000_000
GAZE = [BASE + 10_000_000, BASE + 150_000_000]
HANDS = [BASE + 20_000_000, BASE + 180_000_000]


class Provider:
    labels = {"mic": "mic", "eyegaze": "gaze", "handtracking": "hands"}

    def get_stream_id_from_label(self, label):
        return self.labels.get(label)

    def get_num_data(self, stream):
        return {"rgb": 4, "mic": 8, "gaze": 2, "hands": 2}[stream]

    def get_timestamps_ns(self, stream, *_):
        return {"rgb": RGB, "gaze": GAZE, "hands": HANDS}[stream]

    def get_image_data_by_index(self, *_):
        return SimpleNamespace(to_numpy_array=lambda: np.zeros((48, 64, 3), np.uint8)), None

    def get_audio_configuration(self, _):
        return SimpleNamespace(sample_rate=RATE, num_channels=CHANNELS)

    def get_audio_data_by_index(self, _, index):
        start = AUDIO_START + index * 50_000_000
        stamps = [start + n * 125_000 for n in range(BLOCK)]
        # Channels hold 0..7 times 100, so the mono mix of every sample is 350.
        data = [channel * 100 for _ in range(BLOCK) for channel in range(CHANNELS)]
        return SimpleNamespace(data=data), SimpleNamespace(capture_timestamps_ns=stamps)

    def get_eye_gaze_data_by_index(self, _, index):
        return SimpleNamespace(
            yaw=0.1 * index,
            pitch=-0.2,
            depth=0.5,
            combined_gaze_valid=True,
            spatial_gaze_point_in_cpf=[0.0, -0.1, 0.5],
            spatial_gaze_point_valid=True,
            vergence=SimpleNamespace(left_blink=False, right_blink=index == 1),
        )

    def get_hand_pose_data_by_index(self, _, index):
        hand = SimpleNamespace(
            confidence=0.9,
            get_wrist_position_device=lambda: [1.0, 2.0, 3.0],
            get_palm_position_device=lambda: [4.0, 5.0, 6.0],
            landmark_positions_device=[[0.01 * n, 0.0, 0.0] for n in range(21)],
        )
        return SimpleNamespace(left_hand=None if index == 0 else hand, right_hand=hand)


def vrs_file(monkeypatch, name="session.vrs"):
    monkeypatch.setattr(vrs_export, "vrs_provider", lambda _: (Provider(), "rgb"))
    (VRS / name).write_bytes(b"simulated provider input")
    return name


def finish(client, name, settings):
    response = client.post(f"/api/vrs/{name}/convert", json=settings)
    assert response.status_code == 200, response.text
    job = response.json()
    for _ in range(600):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] not in {"queued", "running"}:
            return job
        time.sleep(0.05)
    raise AssertionError("Conversion did not finish.")


def test_vrs_converts_into_data_and_aligns_audio_and_csvs(client, monkeypatch):
    name = vrs_file(monkeypatch)
    job = finish(client, name, {"audio": True, "gain_db": 0, "eye_gaze": True, "hands": True})
    assert job["status"] == "completed", job["error"]
    manifest = job["result"]
    assert manifest["mp4"] == "session.mp4"
    assert manifest["files"] == ["eye_gaze.csv", "hand_tracking.csv"]
    assert manifest["time_zero_device_ns"] == BASE

    video = DATA / "session.mp4"
    streams = json.loads(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(video)],
            capture_output=True,
            check=True,
        ).stdout
    )["streams"]
    assert sorted(s["codec_type"] for s in streams) == ["audio", "video"]
    assert media.mp4_times(str(video), "check") == [0, 100, 200, 300]
    audio = next(s for s in streams if s["codec_type"] == "audio")
    assert abs(float(audio["duration"]) - 0.3) < 0.1

    # The MP4 is in Data Library, ready to annotate.
    library = client.get("/api/library").json()["assets"]
    assert [a["path"] for a in library] == ["session.mp4"]

    folder = WORK / "exports" / "session"
    with (folder / "eye_gaze.csv").open() as file:
        gaze = list(csv.DictReader(file))
    assert [row["device_time_ns"] for row in gaze] == [str(t) for t in GAZE]
    assert [row["video_ms"] for row in gaze] == ["10.0", "150.0"]
    assert [row["right_blink"] for row in gaze] == ["0", "1"]

    with (folder / "hand_tracking.csv").open() as file:
        hands = list(csv.DictReader(file))
    assert [row["video_ms"] for row in hands] == ["20.0", "180.0"]
    assert hands[0]["left_confidence"] == "" and hands[0]["right_wrist_x_m"] == "1.0"
    assert hands[1]["left_lm20_x_m"] == "0.2"

    [listed] = client.get("/api/vrs").json()
    assert listed["mp4_exists"] and listed["mp4_asset_id"] == library[0]["id"]
    assert listed["export"]["files"] == manifest["files"]
    assert listed["job"]["status"] == "completed"
    download = client.get(f"/api/vrs/{name}/files/eye_gaze.csv")
    assert download.status_code == 200 and "attachment" in download.headers["content-disposition"]
    assert client.get(f"/api/vrs/{name}/files/manifest.json").status_code == 404

    # Never overwrite an MP4 that may already be annotated.
    again = client.post(f"/api/vrs/{name}/convert", json={})
    assert again.status_code == 409 and "already exists" in again.json()["detail"]


def test_audio_mix_is_placed_from_first_rgb_frame(tmp_path):
    output = tmp_path / "audio.wav"
    vrs_export.audio_wav(Provider(), BASE, 300, output)
    with wave.open(str(output)) as file:
        assert file.getframerate() == RATE and file.getnchannels() == 1
        samples = np.frombuffer(file.readframes(file.getnframes()), "<i2")
    # 300 ms at 8 kHz; the 50 ms recorded before the first RGB frame is dropped.
    assert len(samples) == 2400 and (samples == 350).all()


def test_vrs_video_only_and_missing_stream(client, monkeypatch):
    name = vrs_file(monkeypatch)
    job = finish(client, name, {"audio": False, "eye_gaze": False, "hands": False})
    assert job["status"] == "completed", job["error"]
    assert job["result"]["files"] == []
    other = vrs_file(monkeypatch, "other.vrs")
    monkeypatch.setattr(Provider, "labels", {})
    job = finish(client, other, {"audio": False, "eye_gaze": True, "hands": False})
    assert job["status"] == "failed" and "no eyegaze data" in job["error"]
    assert not (DATA / "other.mp4").exists()


def test_vrs_names_are_checked_and_library_is_mp4_only(client, video):
    assert client.post("/api/vrs/missing.vrs/convert", json={}).status_code == 404
    assert client.post("/api/vrs/notes.txt/convert", json={}).status_code == 400
    assert client.post("/api/vrs/..%2Fdata%2Fx.vrs/convert", json={}).status_code in {400, 404}
    (DATA / "stray.vrs").write_bytes(b"not for annotation")
    services.scan()
    assert [a["path"] for a in services.list_assets()] == ["sample.mp4"]
    response = client.post("/api/import", files={"file": ("x.vrs", b"vrs")}, data={"directory": ""})
    assert response.status_code == 400
