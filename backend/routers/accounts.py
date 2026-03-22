"""계정과목 API"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("")
def list_accounts():
    return []
