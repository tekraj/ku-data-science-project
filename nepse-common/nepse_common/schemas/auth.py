from pydantic import BaseModel


class SignInRequest(BaseModel):
    email: str
    password: str


class AuthUser(BaseModel):
    email: str
    display_name: str


class SignInResponse(BaseModel):
    access_token: str
    token_type: str
    user: AuthUser


class MeResponse(BaseModel):
    authenticated: bool
    user: AuthUser
