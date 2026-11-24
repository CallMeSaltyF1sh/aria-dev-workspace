import json
import time

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


def test_prompt_endpoint_matches_what_runs_send(client):
    value = client.get("/api/vlm/prompt").json()
    assert value["template"] == vlm.PROMPT
    assert value["phases"] == vlm.PHASES
    assert value["hash"] == vlm.PROMPT_HASH
    assert value["labels"] == ["P0", "P1", "P2", "P3", "P4", "unclear"]
