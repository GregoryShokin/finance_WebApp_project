from fastapi import APIRouter
router = APIRouter(prefix="/health", tags=["Health"])

@router.get("")
def healthcheck():
    return {"status": "ok"}
