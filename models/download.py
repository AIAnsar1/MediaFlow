from typing import TYPE_CHECKING
from enum import StrEnum
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin
from models.media import Media, MediaSource

if TYPE_CHECKING:
    from models.user import TelegramUser
    from models.bot import Bot


class DownloadStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    CACHED = "cached"  # Served from cache


class Download(Base, TimestampMixin):
    __tablename__ = "downloads"

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("telegram_users.id", ondelete="CASCADE"), index=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id", ondelete="SET NULL"), index=True)

    # Request
    original_url: Mapped[str] = mapped_column(String(2048))
    source: Mapped[MediaSource] = mapped_column(index=True)
    requested_quality: Mapped[str | None] = mapped_column(String(20))

    # Status
    status: Mapped[DownloadStatus] = mapped_column(default=DownloadStatus.PENDING, index=True)
    error_message: Mapped[str | None] = mapped_column(String(512))

    # Performance
    processing_time_ms: Mapped[int | None] = mapped_column()  # How long it took

    # Relations
    user: Mapped["TelegramUser"] = relationship(back_populates="downloads")
    bot: Mapped["Bot"] = relationship(back_populates="downloads")
    media: Mapped["Media | None"] = relationship(back_populates="downloads")
