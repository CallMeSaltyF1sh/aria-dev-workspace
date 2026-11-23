import time

from devworkspace.storage import DATA, WORK


def scan(client):
    response = client.post("/api/scan")
    assert response.status_code == 200, response.text
    return response.json()["assets"][0]


def test_annotation_revision_and_precise_end(client, video):
    asset = scan(client)
    url = f"/api/assets/{asset['id']}/annotation"
    draft = client.get(url).json()
    body = {"revision": 0, "intervals": [
        {"start_ms": 0, "end_ms": 100, "phase": "P1"},
        {"start_ms": 100, "end_ms": draft["duration_ms"], "phase": None},
    ]}
    assert client.put(url, json=body).status_code == 200
    assert client.put(url, json=body).status_code == 409
    saved = client.get(url).json()
    assert saved["intervals"][-1]["end_ms"] == draft["duration_ms"]
    assert (WORK / "annotations" / asset["id"] / "draft.json").exists()
    body["revision"] = 1
    body["intervals"][1]["start_ms"] = 200
    assert client.put(url, json=body).status_code == 400


def test_frames_cache_target_and_clip_start(client, video):
    asset = scan(client)
    url = f"/api/assets/{asset['id']}/frames"
    assert client.get(url).json() == []
    settings = {"target_ms": 0, "count": 5, "spacing_ms": 200, "width": 160}
    def generate():
        job = client.post(url, json=settings).json()
        for _ in range(100):
            current = client.get("/api/jobs/" + job["id"]).json()
            if current["status"] not in {"queued", "running"}:
                assert current["status"] == "completed", current
                return current["result"]
            time.sleep(.05)
        raise AssertionError("Extraction timeout")
    first, second = generate(), generate()
    assert first["id"] == second["id"]
    assert len(client.get(url).json()) == 1
    assert len(first["frames"]) == 3
    assert sum(frame["is_target"] for frame in first["frames"]) == 1
    for frame in first["frames"]:
        response = client.get(f"{url}/{first['id']}/{frame['file']}")
        assert response.headers["content-type"].startswith("image/")


def test_paths_deletion_confirmation_and_symlinks(client, video, tmp_path):
    asset = scan(client)
    assert client.post("/api/directories", json={"path": "../outside"}).status_code == 400
    (DATA / "link.mp4").symlink_to(video)
    assert client.post("/api/scan").status_code == 200
    preview = client.post("/api/deletion-preview", json={"ids": [asset["id"]]}).json()
    assert client.post("/api/delete", json={"ids": [asset["id"]], "token": "bad"}).status_code == 400
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
    assert client.patch("/api/directories", json={"path": "development", "new_name": "training"}).status_code == 200
    assert client.get("/api/library").json()["assets"][0]["id"] == asset["id"]
    with (DATA / "training" / video.name).open("rb") as stream:
        response = client.post("/api/import", files={"file": ("sample.mp4", stream)},
                               data={"directory": "training"})
    assert response.status_code == 409


def test_media_range(client, video):
    asset = scan(client)
    response = client.get(f"/api/assets/{asset['id']}/media", headers={"Range": "bytes=0-99"})
    assert response.status_code == 206
    assert len(response.content) == 100
    timestamps = client.get(f"/api/assets/{asset['id']}/timestamps").json()
    assert timestamps[:3] == [0, 100, 200]
