# app/schemas.py
from pydantic import BaseModel, Field

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=6)
    role: str = Field(default="officer")

class ForgotRequest(BaseModel):
    username: str

class ResetRequest(BaseModel):
    token: str
    new_password: str
