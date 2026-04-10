"""Repository for subscription channels."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.subscription import SubscriptionChannel
from repositories.base import BaseRepository


class SubscriptionChannelRepository(BaseRepository[SubscriptionChannel]):
    """Data access layer for subscription channels."""

    model = SubscriptionChannel

    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_active_required(self, bot_id: int) -> list[SubscriptionChannel]:
        """Get active required channels for a bot."""
        stmt = (
            select(SubscriptionChannel)
            .where(
                SubscriptionChannel.bot_id == bot_id,
                SubscriptionChannel.is_active == True,  # noqa: E712
            )
            .order_by(SubscriptionChannel.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def toggle_active(self, channel_id: int) -> SubscriptionChannel | None:
        """Toggle is_active flag."""
        channel = await self.get_by_id(channel_id)
        if channel:
            channel.is_active = not channel.is_active
            await self.session.flush()
        return channel
