
import base64
import io
import json

from app import create_app
import app.routes as routes

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9p2nX5wAAAAASUVORK5CYII="
)

def make_app(tmp_path, monkeypatch):
    monkeypatch.setenv("SEA_PAY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SEA_PAY_OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("SEA_PAY_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("SEA_PAY_PDF_TEMPLATE_DIR", str(tmp_path / "pdf_template"))
    monkeypatch.setenv("SEA_PAY_FONT_FILE", str(tmp_path / "font.ttf"))

    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "pdf_template").mkdir(parents=True, exist_ok=True)
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "atgsd_n811.csv").write_text("rate,last,first\nSTG1,DOE,JOHN\n", encoding="utf-8")
    (tmp_path / "pdf_template" / "NAVPERS_1070_613_TEMPLATE.pdf").write_bytes(b"%PDF-1.4\n%stub")
    (tmp_path / "font.ttf").write_bytes(b"stub-font")
    app = create_app()
    app.config.update(TESTING=True)
    return app

def test_health_ready_and_404(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    client = app.test_client()
    assert client.get("/healthz").status_code in (200, 503)
    assert client.get("/readyz").status_code == 200
    res = client.get("/does-not-exist")
    assert res.status_code == 404
    assert res.get_json()["code"] == 404

def test_invalid_upload_releases_lock(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    client = app.test_client()
    res = client.post("/process", data={"files": (io.BytesIO(b"bad"), "bad.exe")}, content_type="multipart/form-data")
    assert res.status_code == 400
    assert routes.processing_active is False

def test_cancel_idle(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    client = app.test_client()
    res = client.post("/cancel_process")
    assert res.status_code == 200
    assert res.get_json()["status"] == "idle"

def test_signature_create_list_assign(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    client = app.test_client()
    payload = {
        "name": "Tester",
        "role": "certifier",
        "signature_base64": base64.b64encode(PNG_1X1).decode("utf-8"),
    }
    res = client.post("/api/signatures/create", json=payload)
    assert res.status_code == 200
    sig_id = res.get_json()["signature_id"]

    res = client.post("/api/signatures/assign", json={
        "member_key": "STG1 DOE,JOHN",
        "location": "toris_certifying_officer",
        "signature_id": sig_id,
    })
    assert res.status_code == 200

    res = client.get("/api/signatures/list?member_key=STG1%20DOE,JOHN")
    assert res.status_code == 200
    body = res.get_json()
    assert body["assignments"]["toris_certifying_officer"] == sig_id
    assert any(item["id"] == sig_id for item in body["signatures"])

def test_signature_rejects_invalid_base64(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    client = app.test_client()
    res = client.post("/api/signatures/create", json={
        "name": "Tester",
        "role": "certifier",
        "signature_base64": "not-base64",
    })
    assert res.status_code == 400
    assert "Invalid" in res.get_json()["message"]

def test_signature_deduplicates_same_image(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    client = app.test_client()
    payload = {
        "name": "Tester",
        "role": "certifier",
        "signature_base64": base64.b64encode(PNG_1X1).decode("utf-8"),
    }
    first = client.post("/api/signatures/create", json=payload)
    second = client.post("/api/signatures/create", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.get_json()["signature_id"] == second.get_json()["signature_id"]

    res = client.get("/api/signatures/list")
    assert res.status_code == 200
    assert len(res.get_json()["signatures"]) == 1

def test_health_includes_version_header(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    client = app.test_client()
    res = client.get("/healthz")
    assert "X-App-Version" in res.headers
