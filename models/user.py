from enum import StrEnum

from sqlalchemy import BigInteger, Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import UUIDBase
from models.bot import Bot
from models.download import Download
from models.ads import AdDelivery


class Language(StrEnum):
    UZ = "uz"
    RU = "ru"
    EN = "en"


class TelegramUser(UUIDBase):
    """
    Telegram users. A user can exist in multiple bots (different records per bot).
    telegram_id + bot_id = unique pair.
    """

    __tablename__ = "telegram_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)

    # Profile
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(20))
    bio: Mapped[str | None] = mapped_column(String(512))
    language: Mapped[str] = mapped_column(String(10), default="ru", index=True)

    # Status
    is_blocked: Mapped[bool] = mapped_column(default=False)
    is_banned: Mapped[bool] = mapped_column(default=False)  # Banned by admin
    is_premium: Mapped[bool] = mapped_column(default=False)

    # Stats
    total_downloads: Mapped[int] = mapped_column(default=0)

    # Relations
    bot: Mapped["Bot"] = relationship(back_populates="users")
    downloads: Mapped[list["Download"]] = relationship(back_populates="user")
    ad_deliveries: Mapped[list["AdDelivery"]] = relationship(back_populates="user")

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p) or "Unknown"
