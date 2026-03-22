"""거래내역 API"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.get("")
def list_transactions():
    return []
