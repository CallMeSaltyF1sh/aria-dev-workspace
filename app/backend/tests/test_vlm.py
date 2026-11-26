import json
import time
import pytest

from devworkspace import vlm
from devworkspace.storage import WORK


def wait(client, job):
    for _ in range(200):
        current = client.get("/api/jobs/" + job["id"]).json()
        if current["status"] not in {"queued", "running"}:
            return current
        time.sleep(0.05)
    raise AssertionError("VLM job timeout")


def test_targets_stay_on_cached_grid():
    cells = vlm.targets(1350, 500, 1000)
    assert [c["target_ms"] for c in cells] == [300, 800, 1200]
    assert cells[0]["context_ms"] == [300, 800, 1300]  # Out-of-range context is dropped.
    assert cells[-1] == {
        "start_ms": 1000,
        "end_ms": 1350,
        "target_ms": 1200,
        "context_ms": [200, 700, 1200],
    }


def test_vlm_run_retries_invalid_output_and_saves(client, video, monkeypatch):
    asset = client.post("/api/scan").json()["assets"][0]
    url = f"/api/assets/{asset['id']}/vlm"
    monkeypatch.setattr(vlm, "api_key", lambda: "")
    assert client.post(url, json={"garment": "shirt"}).status_code == 400

    calls = []

    def fake(model, content):
        calls.append(content)
        target = next(i["text"] for i in content if i.get("text", "").endswith("[TARGET]"))
        if target.startswith("t=0.30s") and len(calls) == 1:
            return "not json"
        return json.dumps({"label": "P1" if target.startswith("t=1.20s") else "P0", "reason": "r"})

    monkeypatch.setattr(vlm, "api_key", lambda: "test")
    monkeypatch.setattr(vlm, "call", fake)
    body = {"garment": "shirt", "step_ms": 500, "context_ms": 1000, "workers": 1}
    job = wait(client, client.post(url, json=body).json())
    assert job["status"] == "completed", job
    assert job["result"]["counts"] == {"valid": 3, "invalid_output": 0, "request_failed": 0}
    assert len(calls) == 4  # One retry with a reminder after the invalid answer.
    assert "previous answer was invalid" in calls[1][-1]["text"]
    runs = client.get(url).json()
    assert [r["id"] for r in runs] == [job["result"]["id"]]
    run = client.get(f"{url}/{runs[0]['id']}").json()
    assert [w["label"] for w in run["windows"]] == ["P0", "P0", "P1"]
    assert run["prompt_id"] == "v1" and run["prompt_hash"] == "ad9618fe50c4"
    assert run["prompt"]["name"] == "DM2350 sliding-window prompt"
    end = run["windows"][-1]["end_ms"]  # Probed duration, not the -t passed to ffmpeg.
    assert run["phases"] == [
        {"label": "P0", "start_ms": 0, "end_ms": 1000},
        {"label": "P1", "start_ms": 1000, "end_ms": end},
    ]
    assert (WORK / "vlm" / asset["id"] / f"{run['id']}.json").exists()
    assert client.get(f"{url}/../../x").status_code == 404


def test_vlm_run_fails_when_every_request_fails(client, video, monkeypatch):
    asset = client.post("/api/scan").json()["assets"][0]

    def broken(model, content):
        raise RuntimeError("HTTP 401: bad key")

    monkeypatch.setattr(vlm, "api_key", lambda: "test")
    monkeypatch.setattr(vlm, "call", broken)
    job = client.post(f"/api/assets/{asset['id']}/vlm", json={"garment": "jacket"}).json()
    job = wait(client, job)
    assert job["status"] == "failed"
    assert "HTTP 401" in job["error"]
    assert job["result"]["status"] == "failed"
    run_id = job["result"]["id"]
    response = client.get(f"/api/assets/{asset['id']}/vlm/{run_id}")
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "failed"
    assert result["counts"]["valid"] == 0
    assert all(w["status"] == "request_failed" and w["error"] for w in result["windows"])
    assert client.get("/api/vlm/runs").json()[0]["id"] == run_id


@pytest.mark.parametrize(
    "answer",
    [
        None,
        [],
        {"label": "other", "reason": "r"},
        {"label": "P0"},
        {"label": "P0", "reason": None},
        {"label": "P0", "reason": []},
        {"label": "P0", "reason": {}},
        {"label": "P0", "reason": 123},
        {"label": "P0", "reason": "  "},
        {"label": "P0", "reason": "x" * 2001},
        {"label": "P0", "reason": "r", "extra": True},
    ],
)
def test_answer_schema_rejects_invalid_fields(answer):
    assert vlm.validate(answer) is not None


def test_invalid_reason_is_preserved_without_breaking_result_detail(client, video, monkeypatch):
    asset = client.post("/api/scan").json()["assets"][0]
    monkeypatch.setattr(vlm, "api_key", lambda: "test")
    raw = json.dumps({"label": "P0", "reason": ["wrong type"]})
    monkeypatch.setattr(vlm, "call", lambda *_: raw)
    url = f"/api/assets/{asset['id']}/vlm"
    job = wait(client, client.post(url, json={"garment": "shirt", "workers": 1}).json())
    assert job["status"] == "failed"
    response = client.get(f"{url}/{job['result']['id']}")
    assert response.status_code == 200
    value = response.json()
    assert value["counts"]["invalid_output"] == len(value["windows"])
    assert value["status"] == "failed"
    for window in value["windows"]:
        assert window["label"] == "invalid_output"
        assert window["reason"] is None
        assert window["raw"] == raw
        assert len(window["attempts"]) == 2
        assert all(a["raw"] == raw and a["error"] for a in window["attempts"])


def test_partial_failures_keep_good_windows_and_mark_partial_run(client, video, monkeypatch):
    asset = client.post("/api/scan").json()["assets"][0]
    monkeypatch.setattr(vlm, "api_key", lambda: "test")

    def fake(_, content):
        if any(i.get("text", "").startswith("t=0.30s [TARGET]") for i in content):
            raise RuntimeError("temporary error")
        return json.dumps({"label": "P2", "reason": "visible action"})

    monkeypatch.setattr(vlm, "call", fake)
    job = wait(
        client,
        client.post(
            f"/api/assets/{asset['id']}/vlm", json={"garment": "shirt", "workers": 1}
        ).json(),
    )
    assert job["status"] == "completed"
    assert job["result"]["status"] == "partially_completed"
    assert job["result"]["counts"] == {"valid": 2, "invalid_output": 0, "request_failed": 1}


def test_models_come_from_env_and_gate_runs(client, video, monkeypatch):
    asset = client.post("/api/scan").json()["assets"][0]
    monkeypatch.setattr(vlm, "api_key", lambda: "test")
    monkeypatch.setenv("VLM_MODELS", " qwen3-vl-plus, Qwen2-VL-7B-Instruct,,qwen3-vl-plus ")
    assert client.get("/api/vlm/config").json()["models"] == [
        "qwen3-vl-plus",
        "Qwen2-VL-7B-Instruct",
    ]
    response = client.post(
        f"/api/assets/{asset['id']}/vlm", json={"garment": "shirt", "model": "other"}
    )
    assert response.status_code == 400
    assert "VLM_MODELS" in response.json()["detail"]
    monkeypatch.delenv("VLM_MODELS")
    assert vlm.models() == ["qwen3-vl-plus"]


def test_concurrent_cache_builds_share_one_result(client, video):
    from concurrent.futures import ThreadPoolExecutor

    from devworkspace import frame_sets
    from devworkspace.storage import asset_row

    asset = asset_row(client.post("/api/scan").json()["assets"][0]["id"])
    with ThreadPoolExecutor(3) as pool:
        results = list(pool.map(lambda _: frame_sets.generate(asset, {"width": 160}), range(3)))
    assert len({r["id"] for r in results}) == 1
    assert all(len(r["frames"]) == 14 for r in results)


def test_call_does_not_wait_after_the_last_attempt(monkeypatch):
    import urllib.error

    sleeps = []

    def offline(*_, **__):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(vlm.urllib.request, "urlopen", offline)
    monkeypatch.setattr(vlm.time, "sleep", sleeps.append)
    try:
        vlm.call("m", [], retries=3)
    except RuntimeError as error:
        assert "offline" in str(error)
    else:
        raise AssertionError("call should fail")
    assert sleeps == [3, 6]


def test_all_runs_lists_runs_from_every_recording(client, video, monkeypatch):
    import shutil

    shutil.copyfile(video, video.with_name("second.mp4"))
    assets = client.post("/api/scan").json()["assets"]
    monkeypatch.setattr(vlm, "api_key", lambda: "test")
    monkeypatch.setattr(
        vlm, "call", lambda model, content: json.dumps({"label": "P0", "reason": "r"})
    )
    body = {"garment": "shirt", "step_ms": 1000, "context_ms": 0, "workers": 1}
    for asset in assets:
        job = wait(client, client.post(f"/api/assets/{asset['id']}/vlm", json=body).json())
        assert job["status"] == "completed", job
    items = client.get("/api/vlm/runs").json()
    assert [i["video_id"] for i in items] == ["second.mp4", "sample.mp4"]  # Newest first.
    assert all(i["prompt_id"] == "v1" and i["counts"]["valid"] == 2 for i in items)
    assert "agreement" not in items[0]
