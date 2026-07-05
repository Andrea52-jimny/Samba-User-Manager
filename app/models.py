from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str = Field(min_length=8)
    expiry_date: str | None = None  # formato YYYY-MM-DD, None = durata infinita
    no_expiry: bool = False


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8)


class SetPermissionRequest(BaseModel):
    username: str
    path: str  # percorso relativo alla condivisione, es. "Foto_Viaggi/2025"
    read: bool = False
    write: bool = False
    delete: bool = False
    recursive: bool = True
