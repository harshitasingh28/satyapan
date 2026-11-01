import time

from fastapi.testclient import TestClient

from satyapan.api.app import app, bucket

client = TestClient(app)


def wait(created: dict, timeout: float = 30) -> dict:
    """Poll a record with the access token returned at creation (records are private since 2.0)."""
    inv_id = created["id"]
    start = time.time()
    while time.time() - start < timeout:
        data = client.get(f"/v1/investigations/{inv_id}", headers={"X-Access-Token": created["access_token"]}).json()
        if data["status"] not in ("queued", "running"):
            return data
        time.sleep(0.2)
    raise AssertionError("investigation did not finish")


def test_text_investigation_end_to_end():
    bucket._state.clear()
    r = client.post("/v1/investigations", data={"text": "PM Kisan Yojana gives ₹10,000. Apply now at http://pmkisan-gov.top/x"})
    assert r.status_code == 202
    data = wait(r.json())
    rep = data["report"]
    assert data["status"] == "done" and rep["verdict"] in ("FAKE", "UNVERIFIED")
    assert rep["claim"]["text"] and rep["trace"] and rep["tool_runs"]
    for st in rep["reason"]:
        assert st["evidence_ids"]


def test_rejects_empty_and_bad_files():
    bucket._state.clear()
    assert client.post("/v1/investigations", data={"text": ""}).status_code == 400
    r = client.post("/v1/investigations", files={"files": ("x.jpg", b"not an image at all", "image/jpeg")})
    data = wait(r.json())
    assert any(t["status"] == "INPUT_ERROR" for t in data["report"]["tool_runs"])


def test_unknown_id_and_path_tricks():
    assert client.get("/v1/investigations/doesnotexist").status_code == 404
    assert client.get("/v1/investigations/..%2F..%2Fetc").status_code == 404


def test_rate_limit():
    bucket._state.clear()
    codes = [client.post("/v1/investigations", data={"text": "hello world test message"}).status_code
             for _ in range(bucket.capacity + 1)]
    assert codes[-1] == 429
    bucket._state.clear()
