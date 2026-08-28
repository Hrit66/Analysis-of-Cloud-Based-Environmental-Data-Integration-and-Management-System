from datetime import datetime, timedelta
from typing import Optional
from jose import jwt, JWTError
from passlib.context import CryptContext
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import get_settings
from app.models.user import UserInDB, UserCreate, UserResponse


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    settings = get_settings()
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


async def get_user_by_email(db: AsyncIOMotorDatabase, email: str) -> Optional[UserInDB]:
    user_doc = await db.users.find_one({"email": email})
    if user_doc:
        user_doc["id"] = str(user_doc.pop("_id"))
        return UserInDB(**user_doc)
    return None


async def create_user(db: AsyncIOMotorDatabase, user_create: UserCreate) -> UserInDB:
    hashed_password = get_password_hash(user_create.password)
    user_doc = {
        "email": user_create.email,
        "full_name": user_create.full_name,
        "is_active": user_create.is_active,
        "is_superuser": user_create.is_superuser,
        "hashed_password": hashed_password,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    result = await db.users.insert_one(user_doc)
    user_doc["_id"] = result.inserted_id
    user_doc["id"] = str(result.inserted_id)
    return UserInDB(**user_doc)


async def authenticate_user(db: AsyncIOMotorDatabase, email: str, password: str) -> Optional[UserInDB]:
    user = await get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def get_current_user(token: str, db: AsyncIOMotorDatabase) -> Optional[UserInDB]:
    settings = get_settings()
    credentials_exception = JWTError("Could not validate credentials")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            return None
    except JWTError:
        return None
    user = await get_user_by_email(db, email)
    return user