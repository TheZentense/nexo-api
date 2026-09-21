from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Area = Literal["education", "health", "environment"]
Status = Literal["pending", "accepted", "rejected"]


class ApplicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    email: EmailStr = Field(max_length=254)
    area: Area
    message: str = Field(default="", max_length=2000)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class StatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status
    version: int = Field(ge=1)


class ApplicationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str
    area: Area
    status: Status
    version: int
    created_at: datetime
    updated_at: datetime


class ApplicationDetail(ApplicationSummary):
    message: str


class ApplicationPage(BaseModel):
    items: list[ApplicationSummary]
    total: int
    page: int
    page_size: int
