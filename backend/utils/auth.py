"""Optional API key authentication for external upload endpoints.

env `FINANCEONE_API_KEY` 가 설정되어 있을 때만 `X-API-Key` 헤더 검증.
설정 안 되어 있으면 통과 — 개발/내부 UI 호출 호환성 보존.

운영 배포 시 반드시 env 설정 권장.
"""

import os
from fastapi import Header, HTTPException, status

API_KEY_ENV = "FINANCEONE_API_KEY"


def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.environ.get(API_KEY_ENV, "").strip()
    if not expected:
        return  # 미설정 — 통과 (dev/internal mode)
    if not x_api_key or x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header",
        )
