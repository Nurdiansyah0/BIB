# Repository Guidelines

## Project Structure & Module Organization
- Source: `app/` (FastAPI). Key modules: `main.py` (app setup), `routers/` (API routes), `models.py` (SQLAlchemy), `schemas.py` (Pydantic), `database.py`, `deps.py`, `settings.py`.
- Templates: `app/templates/` (Jinja2). Static assets: `static/`.
- Entrypoint: `run.py` (runs Uvicorn). Dependencies: `requirements.txt`.
- Local SQLite: `inspeksi.db` (do not commit sensitive data).

## Build, Test, and Development Commands
- Create env and install deps:
  - `python -m venv venv && source venv/bin/activate`
  - `pip install -r requirements.txt`
- Run locally (auto-reload):
  - `python run.py` (default: `http://127.0.0.1:8000`)
  - Or: `uvicorn app.main:app --reload`
- Lint/format (recommended):
  - `pip install black isort flake8`
  - `black app run.py` | `isort app` | `flake8 app`
- Tests (if added): `pytest -q`

## Coding Style & Naming Conventions
- Python 3.10+, 4‑space indentation, UTF-8.
- Names: modules/functions `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE`.
- API: add routes in `app/routers/*.py` using `APIRouter`; mount under `/api` where appropriate.
- Schemas in `schemas.py` (Pydantic), DB models in `models.py` (SQLAlchemy), shared deps in `deps.py`.
- Keep handlers lean; move DB logic to small helpers where needed.

## Testing Guidelines
- Framework: `pytest`; use FastAPI `TestClient` for endpoints and temporary SQLite (`sqlite:///:memory:`) for unit tests.
- Naming: files `tests/test_*.py`; functions `test_*`.
- Aim for coverage of critical paths: auth, permissions, and each router’s happy/error cases.
- Commands: `pytest -q` or `pytest tests/test_auth.py -q`.
- Example test (place in `tests/test_app.py`):
  ```python
  from fastapi.testclient import TestClient
  from app.main import app

  client = TestClient(app)

  def test_login_page_loads():
      resp = client.get("/")
      assert resp.status_code == 200
      assert "Login" in resp.text
  ```

## Commit & Pull Request Guidelines
- Commits: concise, imperative, scoped changes. Prefer Conventional Commits, e.g., `feat(auth): add reset password` or `fix(db): handle thread check`.
- PRs: include description, rationale, screenshots for UI pages (templates), reproduction steps, and linked issues. Add testing notes and any schema changes.

## Security & Configuration Tips
- Set `SECRET_KEY` via environment variable for production; avoid defaults.
- Restrict CORS origins in `main.py` for non-dev.
- Review `inspeksi.db` before committing; exclude sensitive data.
- Cookies: keep `httponly` enabled; enable `secure` behind HTTPS.

## Environment Variables
- Recommended: manage secrets via `.env` and `python-dotenv` in development.
  - Install: `pip install python-dotenv`
  - `.env` example (root):
    ```env
    SECRET_KEY=change-me
    ```
  - Load in `app/settings.py`:
    ```python
    from dotenv import load_dotenv; load_dotenv()
    import os
    SECRET_KEY = os.getenv("SECRET_KEY", SECRET_KEY)
    ```
