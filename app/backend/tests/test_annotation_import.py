import shutil
import json
import pytest

from devworkspace.storage import DATA, WORK, atomic_bytes, atomic_json, draft_path
from devworkspace import annotation_imports, services


def export(client, format):
    response = client.get(f"/api/annotations/export?format={format}")
    assert response.status_code == 200
    return response.content


def reset_annotations(client):
    shutil.rmtree(WORK / "annotations")


def upload(client, path, content, **form):
    return client.post(path, files={"file": ("export", content)}, data=form)


def test_json_and_csv_round_trip_into_a_fresh_workspace(client, video):
    asset = client.post("/api/scan").json()["assets"][0]
    duration = client.get(f"/api/assets/{asset['id']}/annotation").json()["duration_ms"]
    intervals = [
        {"start_ms": 0, "end_ms": 500, "phase": "P1"},
        {"start_ms": 500, "end_ms": duration, "phase": None},
    ]
    url = f"/api/assets/{asset['id']}/annotation"
    assert client.put(url, json={"revision": 0, "intervals": intervals}).status_code == 200
    for format in ("json", "csv"):
        content = export(client, format)
        reset_annotations(client)
        # Another computer: same content under another name gets a new asset ID.
        video.rename(DATA / f"renamed-{format}.mp4")
        local = client.post("/api/scan").json()["assets"][0]
        preview = upload(client, "/api/annotations/import-preview", content).json()
        assert preview["counts"]["new"] == 1, preview
        row = preview["rows"][0]
        assert row["local_path"] == f"renamed-{format}.mp4"
        assert row["unlabeled_count"] == 1
        result = upload(client, "/api/annotations/import", content, token=preview["token"]).json()
        assert result == {"imported": 1, "skipped": 0}
        saved = client.get(f"/api/assets/{local['id']}/annotation").json()
        assert saved["intervals"] == intervals and saved["revision"] == 1
        again = upload(client, "/api/annotations/import-preview", content).json()
        assert again["counts"]["identical"] == 1
        video = DATA / f"renamed-{format}.mp4"


def test_conflicts_are_skipped_unless_overwrite_is_chosen(client, video):
    asset = client.post("/api/scan").json()["assets"][0]
    url = f"/api/assets/{asset['id']}/annotation"
    draft = client.get(url).json()
    draft["intervals"][0]["phase"] = "P2"
    client.put(url, json={"revision": 0, "intervals": draft["intervals"]})
    content = export(client, "json")
    draft["intervals"][0]["phase"] = "P3"
    client.put(url, json={"revision": 1, "intervals": draft["intervals"]})

    preview = upload(client, "/api/annotations/import-preview", content).json()
    assert preview["rows"][0]["status"] == "conflict"
    skipped = upload(client, "/api/annotations/import", content, token=preview["token"]).json()
    assert skipped == {"imported": 0, "skipped": 1}
    assert client.get(url).json()["intervals"][0]["phase"] == "P3"
    applied = upload(
        client,
        "/api/annotations/import",
        content,
        token=preview["token"],
        overwrite=[asset["id"]],
    ).json()
    assert applied["imported"] == 1
    assert client.get(url).json()["intervals"][0]["phase"] == "P2"
    # The preview is stale now: the local revision moved on.
    stale = upload(client, "/api/annotations/import", content, token=preview["token"])
    assert stale.status_code == 409


def test_unmatched_ambiguous_and_invalid_records(client, video):
    asset = client.post("/api/scan").json()["assets"][0]
    url = f"/api/assets/{asset['id']}/annotation"
    draft = client.get(url).json()
    draft["intervals"][0]["phase"] = "P0"
    client.put(url, json={"revision": 0, "intervals": draft["intervals"]})
    import json

    value = json.loads(export(client, "json"))
    good = value["records"][0]
    gap = json.loads(json.dumps(good))
    gap["intervals"][0]["end_ms"] -= 100
    unknown = good | {"source_hash": "0" * 64, "video_id": "elsewhere.mp4"}
    value["records"] = [unknown, gap]
    preview = upload(client, "/api/annotations/import-preview", json.dumps(value).encode()).json()
    assert [r["status"] for r in preview["rows"]] == ["no_match", "invalid"]
    assert "cover" in preview["rows"][1]["message"]

    shutil.copyfile(video, DATA / "copy.mp4")
    client.post("/api/scan")
    value["records"] = [good | {"video_id": "other-name.mp4"}]
    preview = upload(client, "/api/annotations/import-preview", json.dumps(value).encode()).json()
    assert preview["rows"][0]["status"] == "ambiguous"
    # The original filename picks one of the identical copies.
    value["records"] = [good, good]
    preview = upload(client, "/api/annotations/import-preview", json.dumps(value).encode()).json()
    assert [r["status"] for r in preview["rows"]] == ["identical", "invalid"]


def test_rejects_files_that_are_not_exports(client):
    for content in (b"not,a,csv\n1,2,3\n", b'{"kind": "other"}', b"[1]", b"\xff\xfe"):
        response = upload(client, "/api/annotations/import-preview", content)
        assert response.status_code == 400, content


def pair_preview(client, video, existing=True):
    shutil.copyfile(video, DATA / "second.mp4")
    assets = client.post("/api/scan").json()["assets"]
    for asset in assets:
        url = f"/api/assets/{asset['id']}/annotation"
        draft = client.get(url).json()
        draft["intervals"][0]["phase"] = "P0"
        assert (
            client.put(url, json={"revision": 0, "intervals": draft["intervals"]}).status_code
            == 200
        )
    content = export(client, "json")
    if existing:
        for asset in assets:
            url = f"/api/assets/{asset['id']}/annotation"
            draft = client.get(url).json()
            draft["intervals"][0]["phase"] = "P1"
            assert (
                client.put(url, json={"revision": 1, "intervals": draft["intervals"]}).status_code
                == 200
            )
    else:
        reset_annotations(client)
    preview = upload(client, "/api/annotations/import-preview", content).json()
    return assets, content, preview


def test_all_import_sources_checked_before_any_write(client, video):
    assets, content, preview = pair_preview(client, video)
    before = {a["id"]: draft_path(a["id"]).read_bytes() for a in assets}
    (DATA / "second.mp4").write_bytes(b"replaced after preview")
    response = upload(
        client,
        "/api/annotations/import",
        content,
        token=preview["token"],
        overwrite=[a["id"] for a in assets],
    )
    assert response.status_code == 400
    assert {a["id"]: draft_path(a["id"]).read_bytes() for a in assets} == before


@pytest.mark.parametrize("existing", [True, False])
def test_import_write_failure_rolls_back_existing_and_new_drafts(
    client, video, monkeypatch, existing
):
    assets, content, preview = pair_preview(client, video, existing)
    before = {a["id"]: draft_path(a["id"]).read_bytes() if existing else None for a in assets}
    original = services.save_draft
    calls = 0

    def fail_after_write(*args):
        nonlocal calls
        result = original(*args)
        calls += 1
        if calls == 2:
            raise OSError("simulated storage failure after a draft write")
        return result

    monkeypatch.setattr(services, "save_draft", fail_after_write)
    response = upload(
        client,
        "/api/annotations/import",
        content,
        token=preview["token"],
        overwrite=[a["id"] for a in assets],
    )
    assert response.status_code == 409
    assert "restored" in response.json()["detail"]
    for asset in assets:
        path = draft_path(asset["id"])
        assert (path.read_bytes() if path.exists() else None) == before[asset["id"]]


def test_interrupted_import_journal_is_recovered(client, video):
    assets, _, _ = pair_preview(client, video)
    asset = assets[0]
    path = draft_path(asset["id"])
    before = path.read_bytes()
    folder = WORK / "annotation_imports" / "interrupted-test"
    atomic_bytes(folder / f"{asset['id']}.json", before)
    atomic_json(
        folder / "journal.json",
        {"state": "pending", "assets": [{"asset_id": asset["id"], "existed": True}]},
    )
    changed = json.loads(before)
    changed["revision"] += 1
    changed["intervals"][0]["phase"] = "P4"
    atomic_json(path, changed)
    annotation_imports.recover_pending()
    assert path.read_bytes() == before
    assert json.loads((folder / "journal.json").read_text())["state"] == "rolled_back"
    annotation_imports.recover_pending()  # Recovery is idempotent.
    assert path.read_bytes() == before
