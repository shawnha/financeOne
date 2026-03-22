"""재무제표 API"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/statements", tags=["statements"])


@router.get("")
def list_statements():
    return []
