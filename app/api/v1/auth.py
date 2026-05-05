from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.models.user import User
from app.schemas.auth import (
    RefreshRequest,
    TokenResponse,
    UserLoginRequest,
    UserMeResponse,
    UserRegisterRequest,
)
from app.services.auth_service import (
    AuthService,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidPasswordError,
    RefreshTokenInvalidError,
    RefreshTokenReusedError,
    UserAlreadyExistsError,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


def _device_label(request: Request) -> str | None:
    return request.headers.get("user-agent")


@router.post("/register", response_model=UserMeResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_REGISTER)
def register_user(request: Request, payload: UserRegisterRequest, db: Session = Depends(get_db)):
    try:
        return AuthService(db).register(email=payload.email, password=payload.password, full_name=payload.full_name)
    except UserAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidPasswordError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
def login_user(request: Request, payload: UserLoginRequest, db: Session = Depends(get_db)):
    try:
        access, refresh = AuthService(db).login(
            email=payload.email,
            password=payload.password,
            device_label=_device_label(request),
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except InactiveUserError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_REFRESH)
def refresh_tokens(request: Request, payload: RefreshRequest, db: Session = Depends(get_db)):
    """Rotate refresh token. Not protected by `get_current_user` — the access
    token is allowed to be expired here, that is the whole point."""
    try:
        access, refresh = AuthService(db).refresh(
            refresh_token=payload.refresh_token,
            device_label=_device_label(request),
        )
    except (RefreshTokenInvalidError, RefreshTokenReusedError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, db: Session = Depends(get_db)):
    """Revoke a refresh token. Idempotent — unknown/invalid tokens still 204
    so the frontend logout flow never has to special-case anything."""
    AuthService(db).logout(refresh_token=payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserMeResponse)
def auth_me(current_user: User = Depends(get_current_user)):
    return current_user
