from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Title = Annotated[str, Field(min_length=1, max_length=200)]
Slug = Annotated[str, Field(min_length=1, max_length=220, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
Status = Literal["draft", "published", "archived"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CategoryInput(Input):
    name: str = Field(min_length=1, max_length=80)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class CategoryOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    slug: str


class ProjectCreate(Input):
    title: Title
    slug: Slug
    category_id: UUID | None = None
    project_date: date | None = None
    short_description: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=30000)
    location: str | None = Field(default=None, max_length=250)
    beneficiaries_count: int | None = Field(default=None, ge=0, le=2147483647)
    progress_percent: int = Field(default=0, ge=0, le=100)


class VersionInput(Input):
    version: int = Field(ge=1)


class ProjectPatch(VersionInput):
    title: Title | None = None
    slug: Slug | None = None
    category_id: UUID | None = None
    project_date: date | None = None
    short_description: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=30000)
    location: str | None = Field(default=None, max_length=250)
    beneficiaries_count: int | None = Field(default=None, ge=0, le=2147483647)
    progress_percent: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def validate_changes(self):
        if not self.model_fields_set - {"version"}:
            raise ValueError("Provide at least one field to update")
        for field in ("title", "slug", "progress_percent"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class ProjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    slug: str
    category_id: UUID | None
    project_date: date | None
    short_description: str | None
    location: str | None
    beneficiaries_count: int | None
    progress_percent: int


class ProjectDetail(ProjectSummary):
    description: str | None


class AdminProject(ProjectDetail):
    status: Status
    version: int
    created_at: datetime
    updated_at: datetime


class PublicPage(BaseModel):
    items: list[ProjectSummary]
    total: int
    page: int
    page_size: int


class AdminPage(BaseModel):
    items: list[AdminProject]
    total: int
    page: int
    page_size: int


class Dashboard(BaseModel):
    total: int
    draft: int
    published: int
    archived: int
    recent: list[AdminProject]
