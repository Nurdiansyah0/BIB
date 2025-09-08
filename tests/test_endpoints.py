import random
import string

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def random_username(prefix: str = "user_") -> str:
    return prefix + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


def test_terminals_list_ok():
    resp = client.get("/api/terminals")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_register_and_login_flow():
    username = random_username()
    # Register
    r1 = client.post(
        "/api/register",
        json={
            "username": username,
            "password": "StrongPass123!",
        },
    )
    assert r1.status_code in (200, 201)

    # Login
    r2 = client.post(
        "/api/login",
        json={
            "username": username,
            "password": "StrongPass123!",
        },
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body.get("message") == "Login ok"
    assert body.get("role") is not None


def test_dashboard_requires_auth_redirect():
    # Without cookie, expect redirect to login
    resp = client.get("/dashboard", allow_redirects=False)
    assert resp.status_code == 303
