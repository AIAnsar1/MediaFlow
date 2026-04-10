from typing import Optional

from datetime import datetime
from sqlalchemy import BigInteger, String, Boolean, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import UUIDBase


class CacheChannel(UUIDBase):

    # Человекочитаемое название канала (например: "Кэш YouTube")
    name: Mapped[str] = mapped_column(String(255),nullable=False,comment="Человекочитаемое название канала")
    # @username канала (без @), может быть NULL для приватных каналов без юзернейма
    username: Mapped[str | None] = mapped_column(String(255),nullable=True,unique=True,comment="Username канала без символа @")
    # Числовой Telegram ID канала (всегда отрицательный для каналов)
    telegram_id: Mapped[int] = mapped_column(BigInteger,nullable=False,unique=True,comment="Числовой Telegram ID канала")
    # Описание / заметки
    description: Mapped[str | None] = mapped_column(Text,nullable=True,comment="Описание или заметки о канале")
    is_active: Mapped[bool] = mapped_column(Boolean,default=True,server_default="true",nullable=False,comment="Используется ли канал для кэширования")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="Когда в последний раз использовали этот канал для загрузки")

    def __repr__(self) -> str:
        return (
            f"<CacheChannel("
            f"id={self.id}, "
            f"name={self.name!r}, "
            f"telegram_id={self.telegram_id}, "
            f"is_active={self.is_active}"
            f")>")








