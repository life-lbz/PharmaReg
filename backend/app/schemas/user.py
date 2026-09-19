
from pydantic import BaseModel, Field


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=12, max_length=128)
    employee_no: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=128)
    department: str | None = None
    role_codes: list[str] = Field(default_factory=list)
    must_change_pwd: bool = True


class UpdateUserRequest(BaseModel):
    display_name: str | None = None
    department: str | None = None
    status: str | None = None
    role_codes: list[str] | None = None


class UserListItem(BaseModel):
    id: int
    username: str
    employee_no: str
    display_name: str
    department: str | None = None
    status: str
    roles: list[str] = []
