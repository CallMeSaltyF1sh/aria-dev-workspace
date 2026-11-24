import time
import csv
import json

from devworkspace.storage import DATA, WORK


def scan(client):
    response = client.post("/api/scan")
    assert response.status_code == 200, response.text
    return response.json()["assets"][0]


def test_annotation_revision_and_precise_end(client, video):
    asset = scan(client)
    url = f"/api/assets/{asset['id']}/annotation"
    draft = client.get(url).json()
    body = {
        "revision": 0,
        "intervals": [
            {"start_ms": 0, "end_ms": 100, "phase": "P1"},
            {"start_ms": 100, "end_ms": draft["duration_ms"], "phase": None},
        ],
    }
    assert client.put(url, json=body).status_code == 200
    assert client.put(url, json=body).status_code == 409
    saved = client.get(url).json()
    assert saved["intervals"][-1]["end_ms"] == draft["duration_ms"]
    assert (WORK / "annotations" / asset["id"] / "draft.json").exists()
    body["revision"] = 1
    body["intervals"][1]["start_ms"] = 200
    assert client.put(url, json=body).status_code == 400


def test_full_video_frames_pagination_and_cache(client, video):
    asset = scan(client)
    url = f"/api/assets/{asset['id']}/frames"
    assert client.get(url).json() == []
    settings = {"interval_ms": 100, "width": 160}

    def generate():
        job = client.post(url, json=settings).json()
        for _ in range(100):
            current = client.get("/api/jobs/" + job["id"]).json()
            if current["status"] not in {"queued", "running"}:
                assert current["status"] == "completed", current
                return current["result"]
            time.sleep(0.05)
        raise AssertionError("Extraction timeout")

    first, second = generate(), generate()
    assert first["id"] == second["id"]
    assert first["mode"] == "full_video"
    assert first["sample_count"] == 14
    assert first["frame_count"] == 14
    assert "frames" not in first  # Lists and job responses stay compact.
    assert len(client.get(url).json()) == 1
    page = client.get(f"{url}/{first['id']}?page_size=5").json()
    assert len(page["frames"]) == 5
    assert page["page_count"] == 3
    assert page["total"] == 14
    assert [frame["requested_ms"] for frame in page["frames"]] == [0, 100, 200, 300, 400]
    last = client.get(f"{url}/{first['id']}?page=3&page_size=5").json()
    assert len(last["frames"]) == 4
    assert last["frames"][-1]["requested_ms"] == 1300
    assert client.get(f"{url}/{first['id']}?page=4&page_size=5").status_code == 400
    for frame in page["frames"]:
        response = client.get(f"{url}/{first['id']}/{frame['file']}")
        assert response.headers["content-type"].startswith("image/")
        assert frame["width"] == 160
        assert frame["actual_ms"] == frame["requested_ms"]
    manifest_path = WORK / "frames" / asset["id"] / first["id"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    stamp = manifest_path.stat().st_mtime_ns
    assert manifest["schema_version"] == 2
    assert manifest["frames"][0]["requested_times_ms"] == [0]
    generate()
    assert manifest_path.stat().st_mtime_ns == stamp
    # A missing JPEG makes the cache incomplete and must trigger reconstruction.
    (manifest_path.parent / manifest["frames"][0]["file"]).unlink()
    generate()
    assert (manifest_path.parent / manifest["frames"][0]["file"]).exists()
    assert client.post(url, json={"target_ms": 0, "count": 5, "spacing_ms": 100}).status_code == 422


def test_full_video_plan_deduplicates_and_maps_every_sample():
    from devworkspace.frame_sets import plan

    frames = plan([0, 300, 800], 850)
    assert [frame["index"] for frame in frames] == [0, 1, 2]
    assert sorted(t for frame in frames for t in frame["requested_times_ms"]) == list(
        range(0, 850, 100)
    )
    assert frames[0]["requested_times_ms"] == [0, 100]
    assert frames[-1]["actual_ms"] == 800


def test_paths_deletion_confirmation_and_symlinks(client, video, tmp_path):
    asset = scan(client)
    assert client.post("/api/directories", json={"path": "../outside"}).status_code == 400
    (DATA / "link.mp4").symlink_to(video)
    assert client.post("/api/scan").status_code == 200
    preview = client.post("/api/deletion-preview", json={"ids": [asset["id"]]}).json()
    assert (
        client.post("/api/delete", json={"ids": [asset["id"]], "token": "bad"}).status_code == 400
    )
    assert video.exists()
    response = client.post("/api/delete", json={"ids": [asset["id"]], "token": preview["token"]})
    assert response.status_code == 200
    assert not video.exists()
    assert client.get("/api/library").json()["assets"][0]["missing"] == 1


def test_rename_preserves_id_and_import_conflict(client, video):
    asset = scan(client)
    assert client.post("/api/directories", json={"path": "development"}).status_code == 200
    video.rename(DATA / "development" / video.name)
    moved = scan(client)
    assert moved["id"] == asset["id"]
    assert (
        client.patch(
            "/api/directories", json={"path": "development", "new_name": "training"}
        ).status_code
        == 200
    )
    assert client.get("/api/library").json()["assets"][0]["id"] == asset["id"]
    with (DATA / "training" / video.name).open("rb") as stream:
        response = client.post(
            "/api/import", files={"file": ("sample.mp4", stream)}, data={"directory": "training"}
        )
    assert response.status_code == 409


def test_media_range(client, video):
    asset = scan(client)
    response = client.get(f"/api/assets/{asset['id']}/media", headers={"Range": "bytes=0-99"})
    assert response.status_code == 206
    assert len(response.content) == 100
    timestamps = client.get(f"/api/assets/{asset['id']}/timestamps").json()
    assert timestamps[:3] == [0, 100, 200]


def test_duplicate_content_requires_explicit_confirmation(client, video):
    scan(client)
    with video.open("rb") as stream:
        blocked = client.post("/api/import", files={"file": ("copy.mp4", stream)})
    assert blocked.status_code == 409
    assert not (DATA / "copy.mp4").exists()
    with video.open("rb") as stream:
        kept = client.post(
            "/api/import", files={"file": ("copy.mp4", stream)}, data={"allow_duplicate": "true"}
        )
    assert kept.status_code == 200
    assert len(kept.json()["assets"]) == 2


def test_source_replacement_and_parse_errors(client, video):
    asset = scan(client)
    draft = client.get(f"/api/assets/{asset['id']}/annotation").json()
    body = {"revision": 0, "intervals": draft["intervals"]}
    assert client.put(f"/api/assets/{asset['id']}/annotation", json=body).status_code == 200
    video.write_bytes(b"this is not a video")
    # Reject stale saves even before the next directory scan.
    body["revision"] = 1
    assert client.put(f"/api/assets/{asset['id']}/annotation", json=body).status_code == 400
    changed = scan(client)
    assert changed["info"]["status"] == "error"
    assert changed["annotation"] == "source_changed"


def test_csv_migration_preview_is_non_mutating(client, video, tmp_path):
    from devworkspace.migrate_csv import apply_review, review, review_hash

    asset = scan(client)
    csv_file = tmp_path / "old.csv"
    with csv_file.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["video_id", "start_s", "end_s", "phase"])
        writer.writerow([video.name, 0, 2, "P0"])
    value = review(csv_file)
    assert value["records"][0]["change_ms"] < 0
    path = WORK / "annotations" / asset["id"] / "draft.json"
    assert not path.exists()
    import pytest

    with pytest.raises(ValueError, match="checksum"):
        apply_review(value, "wrong")
    assert not path.exists()
    apply_review(value, review_hash(value))
    assert json.loads(path.read_text())["intervals"][0]["end_ms"] == asset["info"]["duration_ms"]
    assert ",2,P0" in csv_file.read_text()


def test_vrs_proxy_adapter_preserves_irregular_timing(client, monkeypatch):
    """Adapter simulation only; this does not validate an actual Aria VRS."""
    import numpy as np
    from devworkspace import media
    from devworkspace.storage import digest

    class Image:
        def to_numpy_array(self):
            return np.zeros((48, 64, 3), dtype=np.uint8)

    base = 3_000_000_000
    times = [base, base + 83_333_333, base + 190_000_000, base + 250_000_000]

    class Provider:
        def get_timestamps_ns(self, *_):
            return times

        def get_image_data_by_index(self, *_):
            return Image(), None

    monkeypatch.setattr(media, "vrs_provider", lambda _: (Provider(), "rgb"))
    source = DATA / "simulation.vrs"
    source.write_bytes(b"simulated provider input")
    output = media.make_proxy(source, {"id": "adapter-test", "hash": digest(source)})
    mapping = json.loads((output.parent / "time_mapping.json").read_text())
    assert len(mapping["frames"]) == len(times)
    for record, stamp in zip(mapping["frames"], times):
        assert record["device_ns"] == stamp
        assert abs(record["media_ms"] - (stamp - base) / 1e6) <= 1
    from devworkspace import frame_sets

    full = frame_sets.generate(
        {
            "id": "adapter-test",
            "path": source.name,
            "hash": digest(source),
            "info": {"duration_ms": 250, "time_basis": "DEVICE_TIME", "rgb_stream": "rgb"},
        },
        {"interval_ms": 100, "width": 160},
    )
    assert full["sample_count"] == 3
    assert [frame["requested_ms"] for frame in full["frames"]] == [0, 100, 200]
    assert [frame["device_time_ns"] for frame in full["frames"]] == times[:3]
    assert [frame["actual_ms"] for frame in full["frames"]] == [0, 83.333333, 190]
