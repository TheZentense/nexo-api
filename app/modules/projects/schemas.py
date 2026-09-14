from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CategoryOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    slug: str


class ProjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    slug: str
    category_id: UUID | None
    project_date: date | None
    short_description: str | None
    progress_percent: int
    beneficiaries_count: int | None


class ProjectDetail(ProjectSummary):
    description: str | None
    location: str | None


class PublicPage(BaseModel):
    items: list[ProjectSummary]
    total: int
    page: int
    page_size: int
