from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class Device(BaseModel):
    device_id: UUID
    device_name: str = Field(min_length=1, max_length=80)
    platform: Literal["windows", "android"]
    device_type: str = "desktop"
    ip: str = ""
    port: int = Field(default=45832, ge=45000, le=45999)
    public_key: str = ""
    protocol_version: Literal[1] = 1


class Metadata(BaseModel):
    transfer_id: UUID
    batch_id: UUID | None = None
    filename: str = Field(min_length=1, max_length=240)
    size: int = Field(ge=0, le=16 * 1024**3)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    mime_type: str = Field(default="application/octet-stream", max_length=120)
    sender_device_id: UUID
    origin_device_id: UUID
    protocol_version: Literal[1] = 1

    @field_validator("filename")
    @classmethod
    def safe_name(cls, value: str) -> str:
        from ..security.files import validate_filename
        return validate_filename(value)


class PairRequest(BaseModel):
    device: Device
    code: str = Field(min_length=6, max_length=128)


class PairConfirm(BaseModel):
    request_id: UUID
    confirmation_token: str = Field(min_length=32, max_length=128)
