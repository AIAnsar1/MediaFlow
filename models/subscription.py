"""Required subscription channels — users must subscribe to use the bot."""

from enum import StrEnum
from sqlalchemy import String, BigInteger, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


class SubscriptionStatus(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class SubscriptionChannel(Base, TimestampMixin):
    """Channels that users must subscribe to before using the bot."""
    __tablename__ = "subscription_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    channel_chat_id: Mapped[int] = mapped_column(BigInteger)  # Telegram channel/group chat ID
    channel_username: Mapped[str | None] = mapped_column(String(128))  # @username (without @)
    channel_title: Mapped[str | None] = mapped_column(String(256))  # Human-readable name
    status: Mapped[SubscriptionStatus] = mapped_column(default=SubscriptionStatus.REQUIRED)
    is_active: Mapped[bool] = mapped_column(default=True)

    def __repr__(self) -> str:
        return f"<SubscriptionChannel(id={self.id}, chat_id={self.channel_chat_id}, title='{self.channel_title}')>"
