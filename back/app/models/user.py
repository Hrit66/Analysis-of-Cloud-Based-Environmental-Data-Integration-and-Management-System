from datetime import datetime
from enum import Enum
from typing import Optional

from bson import ObjectId
from pydantic import BaseModel, EmailStr, Field

from app.models.dataset import PyObjectId


class AccountType(str, Enum):
    STUDENT = "student"
    RESEARCHER = "researcher"
    GOVT_AGENCY = "govt_agency"
    GLOBAL_ORG = "global_org"


class PlatformRole(str, Enum):
    USER = "user"
    PLATFORM_ADMIN = "platform_admin"


class OrgRole(str, Enum):
    ORG_ADMIN = "org_admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class UserStatus(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
    PENDING_VERIFICATION = "pending_verification"
    PENDING_APPROVAL = "pending_approval"
    SUSPENDED = "suspended"
    REJECTED = "rejected"


class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    is_active: bool = True
    is_superuser: bool = False
    account_type: AccountType = AccountType.STUDENT
    org_id: Optional[str] = None
    org_role: Optional[OrgRole] = None
    platform_role: PlatformRole = PlatformRole.USER
    orcid: Optional[str] = None
    orcid_verified: bool = False
    institution: Optional[str] = None
    institution_domain: Optional[str] = None
    terms_version: Optional[str] = None
    terms_accepted_at: Optional[datetime] = None
    onboarding_completed: bool = False
    must_change_password: bool = False
    review_required: bool = False
    review_reason: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejected_reason: Optional[str] = None
    signup_source: str = "public"
    supervisor_id: Optional[str] = None
    invite_id: Optional[str] = None
    email_verified: bool = True
    status: UserStatus = UserStatus.ACTIVE
    mfa_enabled: bool = False
    token_version: int = 0
    last_login_at: Optional[datetime] = None


class UserCreate(UserBase):
    password: str


class UserUpdate(UserBase):
    email: Optional[EmailStr] = None
    password: Optional[str] = None


class UserInDB(UserBase):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    hashed_password: str
    mfa_secret: Optional[str] = None
    pending_mfa_secret: Optional[str] = None
    failed_login_attempts: int = 0
    locked_until: Optional[datetime] = None
    quota_overrides: dict[str, int] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {ObjectId: str, datetime: lambda v: v.isoformat()},
    }


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    full_name: Optional[str] = None
    is_active: bool
    is_superuser: bool = False
    account_type: AccountType
    org_id: Optional[str] = None
    org_role: Optional[OrgRole] = None
    platform_role: PlatformRole
    orcid: Optional[str] = None
    orcid_verified: bool = False
    institution: Optional[str] = None
    onboarding_completed: bool = False
    onboarding_required: bool = False
    must_change_password: bool = False
    review_required: bool = False
    review_reason: Optional[str] = None
    email_verified: bool
    status: UserStatus
    mfa_enabled: bool
    created_at: datetime

    model_config = {
        "json_encoders": {datetime: lambda v: v.isoformat()},
    }


class Token(BaseModel):
    access_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int = 0
    mfa_required: bool = False
    mfa_token: Optional[str] = None
    mfa_setup_required: bool = False
    must_change_password: bool = False
    onboarding_required: bool = False


class TokenData(BaseModel):
    email: Optional[str] = None
    user_id: Optional[str] = None
    token_type: Optional[str] = None
