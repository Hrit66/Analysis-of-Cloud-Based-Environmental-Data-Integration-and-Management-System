from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserResponse


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: Optional[str] = None
    signup_type: Literal["student", "researcher"] = "student"
    institution: Optional[str] = None
    terms_accepted: bool = False
    orcid: Optional[str] = None


class VerifyEmailRequest(BaseModel):
    token: str


class MfaVerifyRequest(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=8)


class MfaSetupRequest(BaseModel):
    mfa_token: str


class MfaEnableRequest(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=8)


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class MfaDisableRequest(BaseModel):
    password: str
    code: str = Field(min_length=6, max_length=8)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class MessageResponse(BaseModel):
    message: str
    verification_token: Optional[str] = None
    invite_token: Optional[str] = None


class RegisterResponse(BaseModel):
    message: str = "If the details are valid, check your email for the next step."
    verification_required: bool = True
    verification_token: Optional[str] = None
    status: Optional[str] = None


class VerifyEmailResponse(BaseModel):
    message: str
    status: str
    can_login: bool
    verification_token: Optional[str] = None


class SignupInstitution(BaseModel):
    name: str
    domains: list[str]


class SignupOptionsResponse(BaseModel):
    allowed_domains: list[str]
    institutions: list[SignupInstitution]
    terms_version: str


class AdminUserDecision(BaseModel):
    reason: Optional[str] = None
    account_type: Optional[str] = None


class AdminUserUpdate(BaseModel):
    account_type: Optional[str] = None
    platform_role: Optional[str] = None


class OnboardingResponse(BaseModel):
    message: str
    onboarding_completed: bool


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=10, max_length=128)
