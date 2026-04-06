from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import String, Text, BigInteger, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from models.download import Download


class MediaSource(StrEnum):
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    PINTEREST = "pinterest"
    TWITTER = "twitter"
    REDDIT = "reddit"
    OTHER = "other"


class MediaType(StrEnum):
    VIDEO = "video"
    PHOTO = "photo"
    AUDIO = "audio"
    DOCUMENT = "document"


class MediaQuality(StrEnum):
    Q_360P = "360p"
    Q_480P = "480p"
    Q_720P = "720p"
    Q_1080P = "1080p"
    Q_1440P = "1440p"
    Q_2160P = "2160p"
    Q_BEST = "best"
    Q_AUDIO = "audio"


class Media(Base, TimestampMixin):
    """Cache for downloaded media - stored in Telegram channel"""
    __tablename__ = "media"
    __table_args__ = (
        UniqueConstraint("original_url", "quality", "media_type", name="uq_media_url_quality_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # Original source
    source: Mapped[MediaSource] = mapped_column(index=True)
    original_url: Mapped[str] = mapped_column(String(2048), index=True)
    original_id: Mapped[str | None] = mapped_column(String(256), index=True)  # ID from source platform

    # Telegram cache (stored in private channel)
    telegram_file_id: Mapped[str | None] = mapped_column(String(256), index=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)  # Storage channel ID
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)

    # Meta
    title: Mapped[str | None] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[MediaType] = mapped_column(index=True)
    quality: Mapped[str | None] = mapped_column(String(20), index=True)  # 360p, 720p, audio

    # File info
    duration: Mapped[int | None] = mapped_column(Integer)  # seconds
    file_size: Mapped[int | None] = mapped_column(BigInteger)  # bytes
    thumbnail_url: Mapped[str | None] = mapped_column(String(2048))

    # Stats
    download_count: Mapped[int] = mapped_column(default=0)

    # Relations
    downloads: Mapped[list["Download"]] = relationship(back_populates="media")

    def __repr__(self) -> str:
        return f"<Media(id={self.id}, source='{self.source}', type='{self.media_type}', quality='{self.quality}')>"
