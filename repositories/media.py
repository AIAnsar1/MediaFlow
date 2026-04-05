from sqlalchemy import select, func
from src.repositories.base import BaseRepository
from src.models import Media, MediaSource, MediaType


class MediaRepository(BaseRepository[Media]):
    model = Media

    async def find_cached(
        self,
        original_url: str,
        quality: str | None = None,
        media_type: MediaType | None = None,
    ) -> Media | None:
        """Найти закешированное медиа"""
        filters = {"original_url": original_url, "telegram_file_id__is_null": False}
        if quality:
            filters["quality"] = quality
        if media_type:
            filters["media_type"] = media_type

        return await self.get_one(**filters)

    async def create_or_update_cache(
        self,
        original_url: str,
        source: MediaSource,
        media_type: MediaType,
        quality: str | None = None,
        **data,
    ) -> tuple[Media, bool]:
        """Создать или обновить кеш"""
        return await self.upsert(
            lookup={
                "original_url": original_url,
                "quality": quality,
                "media_type": media_type,
            },
            defaults={
                "source": source,
                **data,
            },
        )

    async def increment_downloads(self, media_id: int) -> None:
        """Увеличить счётчик загрузок"""
        media = await self.get_by_id(media_id)
        if media:
            media.download_count += 1
            await self.session.flush()

    async def get_stats_by_source(self) -> dict[str, int]:
        """Статистика загрузок по источникам"""
        stmt = (
            select(Media.source, func.sum(Media.download_count))
            .group_by(Media.source)
        )
        result = await self.session.execute(stmt)
        return {source.value: count or 0 for source, count in result.all()}

    async def get_popular(self, limit: int = 10) -> list[Media]:
        """Популярные медиа"""
        return list(await self.filter(
            limit=limit,
            order_by="download_count",
            desc=True,
            telegram_file_id__is_null=False,
        ))

    async def cleanup_old_uncached(self, days: int = 30) -> int:
        """Удалить старые записи без кеша"""
        from datetime import datetime, timedelta

        cutoff = datetime.now() - timedelta(days=days)
        return await self.delete_many(
            telegram_file_id__is_null=True,
            created_at__lt=cutoff,
        )
