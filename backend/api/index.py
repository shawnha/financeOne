"""Vercel Python Serverless Function entry point.

Vercel Root=backend 환경에서 build 후 구조:
    /var/task/
      api/index.py
      main.py
      routers/...
      services/...

`from backend.X` import (108 occurrences) 를 작동시키기 위해
sys.modules 에 'backend' 가짜 namespace package 등록.
"""
import os
import sys
import types
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND_ROOT = _HERE.parent

if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

if "backend" not in sys.modules:
    backend_pkg = types.ModuleType("backend")
    backend_pkg.__path__ = [str(_BACKEND_ROOT)]
    sys.modules["backend"] = backend_pkg

# Vercel serverless: scheduler 비활성화 (cold start 마다 종료됨)
os.environ.setdefault("DISABLE_SCHEDULER", "1")

# ASGI app 로드. import 실패 시 fallback 으로 에러 응답.
try:
    from backend.main import app  # noqa: E402
except Exception as e:
    import traceback
    _err_tb = traceback.format_exc()
    from fastapi import FastAPI

    app = FastAPI(title="FinanceOne (import failed)")

    @app.get("/")
    @app.get("/{path:path}")
    def _import_failed(path: str = ""):
        return {
            "status": "error",
            "stage": "import_failed",
            "message": str(e),
            "traceback": _err_tb,
        }
