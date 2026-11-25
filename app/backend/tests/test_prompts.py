import json
import time

from conftest import PROMPTS
from devworkspace import prompts, vlm

LEGACY = """You are analysing a short clip from an egocentric (first-person) video.
The camera wearer is dressing a mannequin with a {garment}.
The clip is shown as {n} frames in time order, one every {step:g} s. Each frame is preceded
by its timestamp. The frame marked [TARGET] is at t={target:.2f} s; the other frames are
context only.

Classify the action at the TARGET frame into exactly one phase:
{phases}

Use the context frames to judge how the hands and the garment are moving,
but label only what happens at the TARGET frame.
Base your answer only on what is visible in the frames.

Return only a JSON object in this format:
{{"label": "P0" | "P1" | "P2" | "P3" | "P4" | "unclear",
 "reason": "<one short sentence describing the visible action at the TARGET frame>"}}"""


def draft(client, **changes):
    v1 = client.get("/api/prompts/v1").json()
    return {
        "based_on": "v1",
        "name": "Stricter P1",
        "note": "",
        **{key: v1[key] for key in ("context", "phases", "guidance")},
        **changes,
    }


def test_v1_is_the_prompt_runs_used_before_versions(client):
    v1 = client.get("/api/prompts/v1").json()
    assert v1["template"] == LEGACY
    # Runs saved before versions recorded only this hash.
    assert v1["hash"] == "ad9618fe50c4"
    assert "mannequin with a jacket" in v1["example"]
    assert "[TARGET] is at t=12.30 s" in v1["example"]
    assert client.get("/api/prompts").json()[0]["id"] == "v1"
    assert client.get("/api/prompts/v9").status_code == 404
    assert client.get("/api/prompts/..%2Fsecrets").status_code == 404


def test_new_version_is_a_new_file_and_v1_is_untouched(client):
    before = (PROMPTS / "v1.json").read_bytes()
    guidance = draft(client)["guidance"] + "\nIf the garment is still in hand, it is not P3."
    body = draft(client, guidance=guidance, note="P1 vs P3")
    preview = client.post(
        "/api/prompts/preview",
        json={k: body[k] for k in ("context", "phases", "guidance")},
    ).json()
    assert "it is not P3" in preview["example"]
    created = client.post("/api/prompts", json=body).json()
    assert created["id"] == "v2" and created["based_on"] == "v1"
    assert created["hash"] == preview["hash"] != "ad9618fe50c4"
    assert json.loads((PROMPTS / "v2.json").read_text())["note"] == "P1 vs P3"
    assert (PROMPTS / "v1.json").read_bytes() == before
    assert [p["id"] for p in client.get("/api/prompts").json()] == ["v2", "v1"]
    # Saving the same wording again is refused.
    response = client.post("/api/prompts", json=body | {"name": "Again"})
    assert response.status_code == 400 and "identical to v2" in response.json()["detail"]


def test_invalid_wording_is_refused(client):
    cases = [
        ({"context": "Dressing a {garment} in {room}."}, "no other braces"),
        ({"phases": "P0 idle\nP1 grab\nP2 turn\nP3 place\nP4 fix"}, "unclear"),
        ({"phases": "{P0} idle"}, "braces"),
        ({"guidance": "   "}, "empty"),
    ]
    for change, message in cases:
        response = client.post("/api/prompts", json=draft(client, **change))
        assert response.status_code == 400, change
        assert message in response.json()["detail"]
    assert client.post("/api/prompts", json=draft(client, based_on="v7")).status_code == 404
    assert not (PROMPTS / "v2.json").exists()


def test_run_uses_the_chosen_version(client, video, monkeypatch):
    asset = client.post("/api/scan").json()["assets"][0]
    phases = draft(client)["phases"].replace("Acquire garment", "Grab garment")
    client.post("/api/prompts", json=draft(client, phases=phases))
    sent = []

    def fake(model, content):
        sent.append(content[0]["text"])
        return json.dumps({"label": "P1", "reason": "r"})

    monkeypatch.setattr(vlm, "api_key", lambda: "test")
    monkeypatch.setattr(vlm, "call", fake)
    url = f"/api/assets/{asset['id']}/vlm"
    for body, expected in (({}, "v2"), ({"prompt_id": "v1"}, "v1")):
        sent.clear()
        job = client.post(url, json={"garment": "shirt", "step_ms": 1000} | body).json()
        for _ in range(200):
            job = client.get("/api/jobs/" + job["id"]).json()
            if job["status"] not in {"queued", "running"}:
                break
            time.sleep(0.05)
        assert job["status"] == "completed", job
        assert job["result"]["settings"]["prompt_id"] == expected
        assert ("Grab garment" in sent[0]) == (expected == "v2")
    response = client.post(url, json={"garment": "shirt", "prompt_id": "v9"})
    assert response.status_code == 404
    assert prompts.latest() == "v2"
