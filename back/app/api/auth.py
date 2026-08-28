from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import db
from app.services.auth import (
    authenticate_user, create_access_token, get_current_user,
    create_user, get_user_by_email
)
from app.config import get_settings
from app.models.user import UserCreate, UserResponse, Token

router = APIRouter(prefix="/api/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_database() -> AsyncIOMotorDatabase:
    return db.db


async def get_current_user_dep(
    token: str = Depends(oauth2_scheme),
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    user = await get_current_user(token, database)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_active_user(
    current_user = Depends(get_current_user_dep),
):
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


@router.post("/register", response_model=UserResponse)
async def register(
    user_create: UserCreate,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    existing = await get_user_by_email(database, user_create.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user = await create_user(database, user_create)
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        created_at=user.created_at,
    )


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    user = await authenticate_user(database, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    settings = get_settings()
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user = Depends(get_current_active_user)):
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        is_superuser=current_user.is_superuser,
        created_at=current_user.created_at,
    )