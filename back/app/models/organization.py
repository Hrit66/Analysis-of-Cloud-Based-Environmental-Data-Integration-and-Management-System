from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from app.models.user import OrgRole


class OrganizationType(str, Enum):
    UNIVERSITY = "university"
    GOVT = "govt"
    NGO = "ngo"
    INTL_ORG = "intl_org"


class OrganizationStatus(str, Enum):
    PENDING = "pending"
    INFO_REQUESTED = "info_requested"
    REJECTED = "rejected"
    VERIFIED = "verified"
    SUSPENDED = "suspended"


class OrganizationSettings(BaseModel):
    require_mfa: bool = True
    allowed_domains: List[str] = Field(default_factory=list)
    default_visibility: str = "private"


class OrganizationBase(BaseModel):
    name: str
    type: OrganizationType
    domains: List[str] = Field(default_factory=list)
    country: Optional[str] = None
    contact_email: EmailStr
    phone: Optional[str] = None
    purpose: Optional[str] = None
    document_url: Optional[str] = None
    contact_verified: bool = False
    contact_verified_at: Optional[datetime] = None
    status: OrganizationStatus = OrganizationStatus.PENDING
    settings: OrganizationSettings = Field(default_factory=OrganizationSettings)


class OrganizationCreate(BaseModel):
    name: str
    type: OrganizationType
    domains: List[str] = Field(default_factory=list)
    country: Optional[str] = None
    contact_email: EmailStr
    phone: Optional[str] = None
    purpose: Optional[str] = None
    document_url: Optional[str] = None
    terms_accepted: bool = False


class OrganizationInDB(OrganizationBase):
    id: str
    requested_by: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


class OrganizationResponse(OrganizationBase):
    id: str
    requested_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    approval_note: Optional[str] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejected_reason: Optional[str] = None


class OrganizationApproval(BaseModel):
    note: Optional[str] = None


class OrganizationDecision(BaseModel):
    reason: str


class OrganizationContactVerify(BaseModel):
    token: str


class OrganizationContactResend(BaseModel):
    contact_email: EmailStr


class OrganizationSetup(BaseModel):
    token: str
    password: str = Field(min_length=10, max_length=128)
    full_name: Optional[str] = None
    terms_accepted: bool = True


class OrganizationSuspend(BaseModel):
    reason: str


class InviteCreate(BaseModel):
    email: EmailStr
    org_role: OrgRole = OrgRole.VIEWER


class InviteResponse(BaseModel):
    id: str
    email: EmailStr
    org_id: str
    org_role: OrgRole
    expires_at: datetime
    token: Optional[str] = None
    status: str = "pending"


class InviteAccept(BaseModel):
    token: str
    password: str = Field(min_length=10, max_length=128)
    full_name: Optional[str] = None
    terms_accepted: bool = False


class MemberRoleUpdate(BaseModel):
    org_role: OrgRole


class MemberResponse(BaseModel):
    user_id: str
    email: EmailStr
    full_name: Optional[str] = None
    account_type: str
    org_role: Optional[OrgRole] = None
    status: str
    mfa_enabled: bool
    created_at: datetime
