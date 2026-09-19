from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


class UserInfo(BaseModel):
    id: int
    username: str
    display_name: str
    employee_no: str
    department: str | None = None
    roles: list[str] = []
    permissions: list[str] = []


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=12, max_length=128)


class SetSignaturePinRequest(BaseModel):
    pin: str = Field(..., min_length=6, max_length=32)
    old_pin: str | None = None
