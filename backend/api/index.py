"""Vercel Python Serverless Function entry point.

Vercel 의 Python runtime 은 /api/*.py 파일을 자동 인식.
이 파일이 ASGI app 인 `app` 을 export 하면 Vercel 이 모든 요청을 라우팅.

Root Directory = backend 로 설정된 Vercel 프로젝트에서 사용.
"""
import os
import sys
from pathlib import Path

# backend/ 디렉토리를 sys.path 에 추가하여 `backend.*` import 가 작동하도록.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Vercel serverless 에서는 background scheduler 가 부적합 (cold start 마다 종료됨).
# scheduler 비활성화 — 정기 sync 는 Vercel Cron Jobs 또는 외부 트리거로 대체.
os.environ["DISABLE_SCHEDULER"] = "1"

# VERSION 파일 경로 (backend/ 외부에 있음 — Vercel Root=backend 일 때 접근 가능해야)
# main.py 의 VERSION 로딩 위치를 신뢰. 없으면 fallback.
try:
    from backend.main import app  # ASGI app
except Exception as e:
    # Fallback: 최소 ASGI app
    from fastapi import FastAPI
    app = FastAPI()
    @app.get("/")
    def root():
        return {"status": "error", "message": f"Failed to load main app: {e}"}
