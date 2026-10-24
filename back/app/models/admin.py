from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.models.user import AccountType, OrgRole, PlatformRole, UserStatus


class AdminUserAction(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    status: Optional[UserStatus] = None
    platform_role: Optional[PlatformRole] = None
    account_type: Optional[AccountType] = None
    org_role: Optional[OrgRole] = None
    quota_overrides: Optional[dict[str, int]] = None


class AdminDatasetAction(BaseModel):
    action: Literal["publish", "unpublish", "set_source"]
    reason: str = Field(min_length=3, max_length=500)
    source_tag: Optional[Literal["real", "synthetic", "modelled"]] = None


class AdminSettingsUpdate(BaseModel):
    registration_mode: Optional[Literal["open", "invite_only", "domain_allowlist"]] = None
    allowed_domains: Optional[list[str]] = None
    mfa_required: Optional[dict[str, bool]] = None
    quota_overrides: Optional[dict[str, dict[str, int]]] = None
    reason: Optional[str] = Field(default=None, max_length=500)
