from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.auth import TokenResponse, UserLoginRequest, UserMeResponse, UserRegisterRequest
from app.services.auth_service import AuthService, InactiveUserError, InvalidCredentialsError, InvalidPasswordError, UserAlreadyExistsError

router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post("/register", response_model=UserMeResponse, status_code=status.HTTP_201_CREATED)
def register_user(payload: UserRegisterRequest, db: Session = Depends(get_db)):
    try:
        return AuthService(db).register(email=payload.email, password=payload.password, full_name=payload.full_name)
    except UserAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidPasswordError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

@router.post("/login", response_model=TokenResponse)
def login_user(payload: UserLoginRequest, db: Session = Depends(get_db)):
    try:
        return TokenResponse(access_token=AuthService(db).login(email=payload.email, password=payload.password))
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except InactiveUserError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

@router.get("/me", response_model=UserMeResponse)
def auth_me(current_user: User = Depends(get_current_user)):
    return current_user
