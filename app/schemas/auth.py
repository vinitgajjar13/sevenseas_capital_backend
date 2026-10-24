from pydantic import BaseModel, Field
from typing import Optional

class LoginRequest(BaseModel):
    username: str = Field(..., description="Username, e.g. Sevenseas")
    password: str = Field(..., min_length=4, description="Trader password")

class ResetPasswordRequest(BaseModel):
    username: str = Field(..., description="Username to reset")
    recovery_code: str = Field(..., description="Security Recovery Code or PIN")
    new_password: str = Field(..., min_length=6, description="New password")

class UserOut(BaseModel):
    id: int
    username: str
    role: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    message: str = "Authentication successful"

