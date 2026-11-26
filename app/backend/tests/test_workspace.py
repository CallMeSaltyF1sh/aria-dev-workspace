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
    import shutil

    asset = scan(client)
    assert client.post("/api/directories", json={"path": "../outside"}).status_code == 400
    (DATA / "link.mp4").symlink_to(video)
    assert client.post("/api/scan").status_code == 200
    preview = client.post("/api/deletion-preview", json={"ids": [asset["id"]]}).json()
    assert (
        client.post("/api/delete", json={"ids": [asset["id"]], "token": "bad"}).status_code == 400
    )
    backup = tmp_path / "backup.mp4"
    shutil.copyfile(video, backup)
    assert video.exists()
    response = client.post("/api/delete", json={"ids": [asset["id"]], "token": preview["token"]})
    assert response.status_code == 200
    assert not video.exists()
    # Unannotated recordings with no VLM runs disappear instead of lingering as missing.
    assert client.get("/api/library").json()["assets"] == []

    # Annotated recordings stay listed as missing until explicitly removed.
    shutil.copyfile(backup, DATA / "annotated.mp4")
    annotated = scan(client)
    draft = client.get(f"/api/assets/{annotated['id']}/annotation").json()
    draft["intervals"][0]["phase"] = "P1"
    assert (
        client.put(
            f"/api/assets/{annotated['id']}/annotation",
            json={"revision": 0, "intervals": draft["intervals"]},
        ).status_code
        == 200
    )
    (DATA / "annotated.mp4").unlink()
    listed = client.post("/api/scan").json()["assets"]
    assert len(listed) == 1 and listed[0]["id"] == annotated["id"] and listed[0]["missing"] == 1
    purge_preview = client.post("/api/deletion-preview", json={"ids": [annotated["id"]]}).json()
    assert purge_preview["files"] == [] and purge_preview["records"] == ["annotated.mp4"]
    assert purge_preview["annotations"] == 1
    purged = client.post(
        "/api/delete", json={"ids": [annotated["id"]], "token": purge_preview["token"]}
    )
    assert purged.status_code == 200
    assert purged.json()["assets"] == []
    assert not (WORK / "annotations" / annotated["id"]).exists()


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


def test_annotation_export_csv_json_and_partial_labels(client, video):
    import io

    renamed = DATA / '衣物, "trial".mp4'
    video.rename(renamed)
    asset = scan(client)
    export = f"/api/annotations/export?asset_id={asset['id']}"
    assert client.get(export + "&format=json").status_code == 400
    endpoint = f"/api/assets/{asset['id']}/annotation"
    draft = client.get(endpoint).json()
    body = {
        "revision": 0,
        "intervals": [
            {"start_ms": 0, "end_ms": 100, "phase": "P1"},
            {"start_ms": 100, "end_ms": draft["duration_ms"], "phase": None},
        ],
    }
    assert client.put(endpoint, json=body).status_code == 200
    saved_file = WORK / "annotations" / asset["id"] / "draft.json"
    before = saved_file.read_bytes()
    response = client.get(export + "&format=json")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    value = response.json()
    assert value["counts"]["recording_count"] == 1
    assert value["counts"]["unlabeled_count"] == 1
    record = value["records"][0]
    assert record["video_id"] == renamed.name
    assert record["annotation_revision"] == 1
    assert record["intervals"] == body["intervals"]
    assert record["source_status"] == "current"
    assert "study" not in record
    assert str(DATA) not in response.text
    csv_response = client.get(export + "&format=csv")
    rows = list(csv.DictReader(io.StringIO(csv_response.content.decode("utf-8-sig"))))
    assert len(rows) == 2
    assert rows[0]["video_id"] == renamed.name
    assert rows[0]["start_ms"] == "0" and rows[0]["end_s"] == "0.100"
    assert rows[1]["phase"] == ""
    assert saved_file.read_bytes() == before


def test_annotation_bulk_export_all_folders_excludes_blank_drafts(client, video):
    import shutil

    first = scan(client)
    (DATA / "test").mkdir()
    shutil.copyfile(video, DATA / "test" / "second.mp4")
    shutil.copyfile(video, DATA / "blank.mp4")
    assets = client.post("/api/scan").json()["assets"]
    for item in assets:
        url = f"/api/assets/{item['id']}/annotation"
        draft = client.get(url).json()
        draft["intervals"][0]["phase"] = None if item["path"] == "blank.mp4" else "unclear"
        assert (
            client.put(url, json={"revision": 0, "intervals": draft["intervals"]}).status_code
            == 200
        )
    summary = client.get("/api/annotations/export-summary").json()
    assert summary["recording_count"] == 2
    assert summary["segment_count"] == 2
    records = client.get("/api/annotations/export?format=json").json()["records"]
    assert {r["video_id"] for r in records} == {first["path"], "test/second.mp4"}
    assert all(r["intervals"][0]["phase"] == "unclear" for r in records)
    assert client.get("/api/annotations/export?format=xml").status_code == 422


def test_annotation_export_preserves_source_warnings(client, video):
    asset = scan(client)
    url = f"/api/assets/{asset['id']}/annotation"
    draft = client.get(url).json()
    draft["intervals"][0]["phase"] = "P0"
    assert client.put(url, json={"revision": 0, "intervals": draft["intervals"]}).status_code == 200
    video.write_bytes(b"changed recording")
    value = client.get("/api/annotations/export?format=json").json()
    assert value["counts"]["changed_source_count"] == 1
    assert value["records"][0]["source_hash"] == asset["hash"]
    video.unlink()
    value = client.get("/api/annotations/export?format=json").json()
    assert value["counts"]["missing_source_count"] == 1
    assert value["records"][0]["source_status"] == "missing"


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


def test_annotation_export_selected_recordings(client, video):
    import shutil

    shutil.copyfile(video, DATA / "second.mp4")
    shutil.copyfile(video, DATA / "blank.mp4")
    assets = {a["path"]: a for a in client.post("/api/scan").json()["assets"]}
    for path, phase in (("sample.mp4", "P1"), ("second.mp4", "P2")):
        url = f"/api/assets/{assets[path]['id']}/annotation"
        draft = client.get(url).json()
        draft["intervals"][0]["phase"] = phase
        client.put(url, json={"revision": 0, "intervals": draft["intervals"]})
    listed = client.get("/api/annotations/exportable").json()
    assert [item["video_id"] for item in listed] == ["sample.mp4", "second.mp4"]
    assert listed[0]["segment_count"] == 1 and listed[0]["source_status"] == "current"

    second = assets["second.mp4"]["id"]
    response = client.get(f"/api/annotations/export?format=json&asset_id={second}")
    assert [r["video_id"] for r in response.json()["records"]] == ["second.mp4"]
    assert f"annotations_{second}_" in response.headers["content-disposition"]
    both = "&".join(f"asset_id={assets[p]['id']}" for p in ("sample.mp4", "second.mp4"))
    response = client.get(f"/api/annotations/export?format=csv&{both}")
    assert "annotations_2-recordings_" in response.headers["content-disposition"]
    assert len(list(csv.DictReader(response.content.decode("utf-8-sig").splitlines()))) == 2
    # A selected recording without a labeled annotation is an error, not silently dropped.
    blank = assets["blank.mp4"]["id"]
    assert (
        client.get(f"/api/annotations/export?format=json&{both}&asset_id={blank}").status_code
        == 400
    )
    assert client.get("/api/annotations/export?format=json&asset_id=missing").status_code == 404
