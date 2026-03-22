"""파일 업로드 API"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/upload", tags=["upload"])


@router.post("")
def upload_file():
    return {"status": "not_implemented"}
