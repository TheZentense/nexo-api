from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VolunteerApplication(Base):
    __tablename__ = "volunteer_applications"
    __table_args__ = (
        CheckConstraint("area IN ('education','health','environment')", name="area_values"),
        CheckConstraint("status IN ('pending','accepted','rejected')", name="status_values"),
        CheckConstraint("version > 0", name="version_positive"),
        Index("ix_volunteer_applications_created_at_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254))
    area: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(String(2000), server_default="")
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    version: Mapped[int] = mapped_column(server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
