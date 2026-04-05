from datetime import date
from sqlalchemy import Date, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base
from models.media import MediaSource


class DailyStats(Base):
    """Daily statistics aggregation"""
    __tablename__ = "daily_stats"
    __table_args__ = (
        UniqueConstraint("date", "bot_id", "source", name="uq_daily_stats"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    bot_id: Mapped[int | None] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    source: Mapped[MediaSource | None] = mapped_column(index=True)  # None = total

    new_users: Mapped[int] = mapped_column(default=0)
    active_users: Mapped[int] = mapped_column(default=0)
    downloads: Mapped[int] = mapped_column(default=0)
    cached_downloads: Mapped[int] = mapped_column(default=0)
    failed_downloads: Mapped[int] = mapped_column(default=0)
