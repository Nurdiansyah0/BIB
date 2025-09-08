from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


def test_login_page_loads():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Login" in resp.text

