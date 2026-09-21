from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ImageVariant(BaseModel):
    label: str
    url: str
    width: int
    height: int
    size_bytes: int


class ImageOutput(BaseModel):
    id: UUID
    status: Literal["pending", "processing", "ready", "failed", "unavailable", "archived"]
    archived_at: datetime | None
    alt_text: str
    position: int
    is_cover: bool
    variants: list[ImageVariant]


class GalleryOutput(BaseModel):
    project_version: int
    cover_image_id: UUID | None
    items: list[ImageOutput]


class GalleryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    image_ids: list[UUID] = Field(max_length=10)
    cover_image_id: UUID | None


class ImageTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: int = Field(ge=1)
    alt_text: str = Field(max_length=250)
