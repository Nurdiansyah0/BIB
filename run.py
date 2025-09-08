import os
import uvicorn
from app.main import app


def _env_bool(name: str, default: bool = True) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    # Allow overriding host/port via environment variables.
    # Precedence: UVICORN_HOST/PORT, then HOST/PORT; defaults to 127.0.0.1:8000.
    # Default to 0.0.0.0 so other devices on the LAN can access it.
    # Override with HOST/UVICORN_HOST for tighter binding.
    host = os.getenv("UVICORN_HOST", os.getenv("HOST", "0.0.0.0"))
    try:
        port = int(os.getenv("UVICORN_PORT", os.getenv("PORT", "8000")))
    except ValueError:
        port = 8000

    reload = _env_bool("RELOAD", True)

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
    )
