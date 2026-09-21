from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProjectVideo(Base):
    __tablename__ = "project_videos"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','processing','ready','failed')", name="status_values"
        ),
        CheckConstraint("size_bytes > 0", name="size_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), index=True
    )
    original_key: Mapped[str] = mapped_column(String(300), unique=True)
    video_key: Mapped[str | None] = mapped_column(String(300))
    poster_key: Mapped[str | None] = mapped_column(String(300))
    size_bytes: Mapped[int]
    status: Mapped[str] = mapped_column(String(20), server_default="pending", index=True)
    error_code: Mapped[str | None] = mapped_column(String(40))
    attempt_id: Mapped[UUID | None]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectImage(Base):
    __tablename__ = "project_images"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','processing','ready','failed')", name="status_values"
        ),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("position >= 0", name="position_nonnegative"),
        Index(
            "uq_project_images_cover",
            "project_id",
            unique=True,
            postgresql_where=text("is_cover"),
            sqlite_where=text("is_cover"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), index=True
    )
    original_key: Mapped[str] = mapped_column(String(300), unique=True)
    variants: Mapped[dict] = mapped_column(JSON, nullable=False, server_default="{}")
    size_bytes: Mapped[int]
    status: Mapped[str] = mapped_column(String(20), server_default="pending", index=True)
    error_code: Mapped[str | None] = mapped_column(String(40))
    attempt_id: Mapped[UUID | None]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    position: Mapped[int] = mapped_column(server_default="0")
    is_cover: Mapped[bool] = mapped_column(server_default="false")
    alt_text: Mapped[str] = mapped_column(String(250), server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
