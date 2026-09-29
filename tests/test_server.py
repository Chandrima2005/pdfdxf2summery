import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import server


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


def test_pages_and_static(client):
    for path in ("/", "/app", "/static/styles.css", "/static/app.js"):
        assert client.get(path).status_code == 200


def test_samples_catalog_starts_with_boards(client):
    cats = client.get("/api/samples").json()["categories"]
    assert [c["id"] for c in cats] == ["db", "plan", "ckt"]
    assert all(c["samples"] for c in cats)


def test_drawing_info_has_board_rows_for_a_board(client):
    info = client.get("/api/drawing/db-001.dxf").json()
    assert info["board"] and info["spec"] and info["examples"]
    assert client.get("/api/drawing/plan-001.dxf").json()["board"] == []


def test_image_and_unknown_ids(client):
    r = client.get("/api/image/db-001.dxf?size=thumb")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert client.get("/api/drawing/..%2F..%2Fsecret.dxf").status_code == 404
    assert client.get("/api/drawing/nope.dxf").status_code == 404


def test_ask_offline_in_desktop_mode(client, monkeypatch):
    monkeypatch.setattr(server, "DESKTOP", True)
    ans = client.post("/api/ask", json={"question": "How many rooms are in this plan?",
                                        "drawing": "plan-001.dxf", "mode": "offline"}).json()
    assert ans["route"] == "compute" and ans["final"]


def test_upload_rejects_other_types(client):
    r = client.post("/api/upload", files={"file": ("notes.txt", b"hi", "text/plain")})
    assert r.status_code == 400


def test_desktop_zip_has_no_secrets(client):
    names = zipfile.ZipFile(io.BytesIO(client.get("/api/download").content)).namelist()
    assert "cad-copilot/run.bat" in names and "cad-copilot/app/web/app.js" in names
    assert not any(n.endswith((".env", ".env.txt")) for n in names)


def test_pdf_drawing_upload_view_and_offline_answer(client, monkeypatch):
    pdf = (server.SAMPLES / "building_spec.pdf").read_bytes()
    r = client.post("/api/upload", files={"file": ("sheet.pdf", pdf, "application/pdf")}, data={"role": "drawing"})
    assert r.status_code == 200
    fid = r.json()["id"]
    info = client.get(f"/api/drawing/{fid}").json()
    assert info["kind"] == "pdf" and info["pages"] >= 1 and info["examples"]
    assert client.get(f"/api/image/{fid}?page=1").headers["content-type"] == "image/png"
    monkeypatch.setattr(server, "DESKTOP", True)
    ans = client.post("/api/ask", json={"question": "What is shown?", "drawing": fid, "mode": "offline"}).json()
    # offline, a text PDF is still answered from its own passages (never from a sample)
    assert ans["route"] == "spec" and ans["sources"] and "sheet.pdf" in ans["text"]


def test_pdf_answer_uses_whole_document(client, monkeypatch):
    """A question about page 2 is answered while page 1 is on screen, and only from the uploaded file."""
    import pymupdf
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Pump P-101 rated 15 kW")
    doc.new_page().insert_text((72, 72), "Valve MOV-22 is fed from MCC-3")
    pdf = doc.tobytes()
    fid = client.post("/api/upload", files={"file": ("two.pdf", pdf, "application/pdf")}, data={"role": "drawing"}).json()["id"]
    seen = {}

    class Fake:
        def complete(self, system, user, png=None):
            seen["user"] = user
            return "MCC-3 (p.2)\nFINAL: MCC-3"
    monkeypatch.setattr(server, "_llm", lambda: (Fake(), None))
    ans = client.post("/api/ask", json={"question": "What feeds MOV-22?", "drawing": fid, "page": 1}).json()
    assert "MCC-3" in seen["user"] and ans["final"] == "MCC-3"
    assert any(s["page"] == 2 for s in ans["sources"])
