import uuid as uuid_lib
from enum import StrEnum
from datetime import datetime
from sqlalchemy import String, Text, ForeignKey, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin
from models.bot import Bot
from models.user import TelegramUser


class AdMediaType(StrEnum):
    NONE = "none"
    PHOTO = "photo"
    VIDEO = "video"
    ANIMATION = "animation"


class AdStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENDING = "sending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Ad(Base, TimestampMixin):
    __tablename__ = "ads"

    id: Mapped[int] = mapped_column(primary_key=True)
    ad_uuid: Mapped[str] = mapped_column(String(36),default=lambda: str(uuid_lib.uuid4()),unique=True,index=True)
    name: Mapped[str] = mapped_column(String(128))  # Internal name for admin

    content: Mapped[str] = mapped_column(Text)  # Message text
    media_type: Mapped[AdMediaType] = mapped_column(default=AdMediaType.NONE)
    media_file_id: Mapped[str | None] = mapped_column(String(256))

    button_text: Mapped[str | None] = mapped_column(String(64))
    button_url: Mapped[str | None] = mapped_column(String(512))

    target_language: Mapped[str | None] = mapped_column(String(10), index=True)  # None = all languages

    status: Mapped[AdStatus] = mapped_column(default=AdStatus.DRAFT)
    is_active: Mapped[bool] = mapped_column(default=True)

    scheduled_at: Mapped[datetime | None] = mapped_column()
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()

    total_recipients: Mapped[int] = mapped_column(default=0)
    sent_count: Mapped[int] = mapped_column(default=0)
    failed_count: Mapped[int] = mapped_column(default=0)

    target_bots: Mapped[list["AdBot"]] = relationship(back_populates="ad",cascade="all, delete-orphan")
    deliveries: Mapped[list["AdDelivery"]] = relationship(back_populates="ad",cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ad_uuid": self.ad_uuid,
            "name": self.name,
            "content": self.content,
            "media_type": self.media_type.value,
            "target_language": self.target_language,
            "status": self.status.value,
            "sent_count": self.sent_count,
        }


class AdBot(Base):
    """Many-to-Many: Ad <-> Bot (which bots will send this ad)"""
    __tablename__ = "ad_bots"

    id: Mapped[int] = mapped_column(primary_key=True)
    ad_id: Mapped[int] = mapped_column(ForeignKey("ads.id", ondelete="CASCADE"), index=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)

    ad: Mapped["Ad"] = relationship(back_populates="target_bots")
    bot: Mapped["Bot"] = relationship()


class AdDelivery(Base, TimestampMixin):
    """Track individual ad deliveries to users"""
    __tablename__ = "ad_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    ad_id: Mapped[int] = mapped_column(ForeignKey("ads.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)

    # Telegram message info (for deletion)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)

    # Status
    is_sent: Mapped[bool] = mapped_column(default=False)
    error_message: Mapped[str | None] = mapped_column(String(256))

    # Relations
    ad: Mapped["Ad"] = relationship(back_populates="deliveries")
    user: Mapped["TelegramUser"] = relationship(back_populates="ad_deliveries")
    bot: Mapped["Bot"] = relationship()
