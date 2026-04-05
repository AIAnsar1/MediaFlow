import asyncio
from datetime import datetime, timedelta
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from src.logging import get_logger
from src.database.connection import db
from src.repositories.uow import UnitOfWork
from src.services import bot_manager, cache
from src.services.rate_limiter import rate_limiter, RateLimitType
from src.models import Ad, AdStatus, User

log = get_logger("workers.tasks")


# === Broadcast Tasks ===

async def broadcast_ad(
    ctx: dict,
    ad_id: int,
    batch_size: int = 25,
    delay_ms: int = 50,
) -> dict[str, Any]:
    """
    Фоновая задача рассылки рекламы

    Args:
        ad_id: ID рекламы
        batch_size: Размер batch
        delay_ms: Задержка между сообщениями (мс)

    Returns:
        {"sent": int, "failed": int, "blocked": int, "duration": float}
    """
    log.info("Starting broadcast", ad_id=ad_id)
    start_time = datetime.now()

    sent = 0
    failed = 0
    blocked = 0

    async with UnitOfWork() as uow:
        # Получаем рекламу
        ad = await uow.ads.get_with_relations(ad_id)
        if not ad:
            log.error("Ad not found", ad_id=ad_id)
            return {"error": "Ad not found"}

        # Обновляем статус
        await uow.ads.update(ad_id, status=AdStatus.SENDING, started_at=datetime.now())
        await uow.commit()

        # Получаем целевых ботов
        bot_ids = await uow.ads.get_target_bot_ids(ad_id)
        if not bot_ids:
            log.error("No target bots", ad_id=ad_id)
            return {"error": "No target bots"}

        # Получаем пользователей
        users = await uow.users.get_users_for_broadcast(bot_ids, ad.target_language)
        total_users = len(users)

        log.info("Broadcasting to users", ad_id=ad_id, total=total_users)

        # Группируем по ботам
        users_by_bot: dict[int, list[User]] = {}
        for user in users:
            users_by_bot.setdefault(user.bot_id, []).append(user)

        # Рассылаем
        for bot_id, bot_users in users_by_bot.items():
            bot = await bot_manager.get_bot_by_id(bot_id)
            if not bot:
                log.warning("Bot not available", bot_id=bot_id)
                failed += len(bot_users)
                continue

            # Обрабатываем batch'ами
            for i in range(0, len(bot_users), batch_size):
                batch = bot_users[i:i + batch_size]

                # Проверяем rate limit
                rate_result = await rate_limiter.check_broadcast(bot_id)
                if not rate_result.allowed:
                    log.warning("Rate limit hit, waiting", seconds=rate_result.retry_after)
                    await asyncio.sleep(rate_result.retry_after)

                # Отправляем batch параллельно
                results = await asyncio.gather(*[
                    _send_ad_to_user(uow, ad, user, bot, delay_ms)
                    for user in batch
                ], return_exceptions=True)

                for user, result in zip(batch, results):
                    if isinstance(result, Exception):
                        failed += 1
                        if isinstance(result, TelegramForbiddenError):
                            blocked += 1
                    elif result:
                        sent += 1
                    else:
                        failed += 1

                # Небольшая пауза между batch'ами
                await asyncio.sleep(0.1)

        # Обновляем статистику
        duration = (datetime.now() - start_time).total_seconds()

        await uow.ads.update(
            ad_id,
            status=AdStatus.COMPLETED,
            completed_at=datetime.now(),
            total_recipients=total_users,
            sent_count=sent,
            failed_count=failed,
        )
        await uow.commit()

    result = {
        "ad_id": ad_id,
        "total": total_users,
        "sent": sent,
        "failed": failed,
        "blocked": blocked,
        "duration": duration,
    }

    log.info("Broadcast completed", **result)
    return result


async def _send_ad_to_user(
    uow: UnitOfWork,
    ad: Ad,
    user: User,
    bot: Bot,
    delay_ms: int,
) -> bool:
    """Отправить рекламу одному пользователю"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.models import AdMediaType

    try:
        # Небольшая задержка для rate limiting
        await asyncio.sleep(delay_ms / 1000)

        # Формируем клавиатуру
        keyboard = None
        if ad.button_text and ad.button_url:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=ad.button_text, url=ad.button_url)
            ]])

        message = None

        # Отправляем в зависимости от типа
        if ad.media_type == AdMediaType.PHOTO:
            message = await bot.send_photo(
                user.telegram_id,
                photo=ad.media_file_id,
                caption=ad.content,
                reply_markup=keyboard,
            )
        elif ad.media_type == AdMediaType.VIDEO:
            message = await bot.send_video(
                user.telegram_id,
                video=ad.media_file_id,
                caption=ad.content,
                reply_markup=keyboard,
            )
        elif ad.media_type == AdMediaType.ANIMATION:
            message = await bot.send_animation(
                user.telegram_id,
                animation=ad.media_file_id,
                caption=ad.content,
                reply_markup=keyboard,
            )
        else:
            message = await bot.send_message(
                user.telegram_id,
                text=ad.content,
                reply_markup=keyboard,
            )

        # Сохраняем delivery
        await uow.ad_deliveries.create_delivery(
            ad_id=ad.id,
            user_id=user.id,
            bot_id=user.bot_id,
            telegram_chat_id=user.telegram_id,
            telegram_message_id=message.message_id,
            is_sent=True,
        )

        return True

    except TelegramForbiddenError:
        # Пользователь заблокировал бота
        await uow.users.update(user.id, is_blocked=True)
        await uow.ad_deliveries.create_delivery(
            ad_id=ad.id,
            user_id=user.id,
            bot_id=user.bot_id,
            telegram_chat_id=user.telegram_id,
            is_sent=False,
            error_message="Bot blocked by user",
        )
        raise

    except Exception as e:
        await uow.ad_deliveries.create_delivery(
            ad_id=ad.id,
            user_id=user.id,
            bot_id=user.bot_id,
            telegram_chat_id=user.telegram_id,
            is_sent=False,
            error_message=str(e)[:256],
        )
        return False


async def delete_ad_messages(
    ctx: dict,
    ad_id: int,
) -> dict[str, Any]:
    """
    Удалить все сообщения рекламы
    """
    log.info("Deleting ad messages", ad_id=ad_id)

    deleted = 0
    failed = 0

    async with UnitOfWork() as uow:
        # Получаем доставки
        deliveries = await uow.ad_deliveries.filter(
            ad_id=ad_id,
            is_sent=True,
        )

        # Группируем по ботам
        deliveries_by_bot: dict[int, list] = {}
        for d in deliveries:
            deliveries_by_bot.setdefault(d.bot_id, []).append(d)

        for bot_id, bot_deliveries in deliveries_by_bot.items():
            bot = await bot_manager.get_bot_by_id(bot_id)
            if not bot:
                failed += len(bot_deliveries)
                continue

            for delivery in bot_deliveries:
                if not delivery.telegram_message_id:
                    continue

                try:
                    await bot.delete_message(
                        delivery.telegram_chat_id,
                        delivery.telegram_message_id,
                    )
                    deleted += 1
                except Exception as e:
                    log.debug("Delete failed", error=str(e))
                    failed += 1

                # Rate limit
                await asyncio.sleep(0.05)

        # Удаляем рекламу из БД
        await uow.ads.delete(ad_id)
        await uow.commit()

    result = {"ad_id": ad_id, "deleted": deleted, "failed": failed}
    log.info("Ad messages deleted", **result)
    return result


# === Cleanup Tasks ===

async def cleanup_temp_files(ctx: dict) -> dict[str, Any]:
    """Очистка временных файлов старше 1 часа"""
    import os
    import shutil
    from pathlib import Path
    from src.config import settings

    log.info("Starting temp files cleanup")

    temp_dir = Path(settings.temp_download_path)
    if not temp_dir.exists():
        return {"cleaned": 0}

    now = datetime.now().timestamp()
    max_age = 3600  # 1 час
    cleaned = 0

    for item in temp_dir.iterdir():
        try:
            mtime = item.stat().st_mtime
            if now - mtime > max_age:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
                cleaned += 1
        except Exception as e:
            log.warning("Cleanup failed", path=str(item), error=str(e))

    log.info("Temp files cleaned", count=cleaned)
    return {"cleaned": cleaned}


async def cleanup_old_downloads(ctx: dict, days: int = 30) -> dict[str, Any]:
    """Очистка старых записей о загрузках"""
    from sqlalchemy import delete
    from src.models import Download

    log.info("Cleaning old downloads", days=days)

    cutoff = datetime.now() - timedelta(days=days)

    async with UnitOfWork() as uow:
        # Удаляем старые записи
        count = await uow.session.execute(
            delete(Download).where(Download.created_at < cutoff)
        )
        await uow.commit()
        deleted = count.rowcount

    log.info("Old downloads cleaned", deleted=deleted)
    return {"deleted": deleted}


# === Stats Tasks ===

async def update_bot_stats(ctx: dict) -> dict[str, Any]:
    """Обновить статистику ботов"""
    from sqlalchemy import select, func
    from src.models import Bot, User, Download

    log.info("Updating bot stats")

    updated = 0

    async with UnitOfWork() as uow:
        bots = await uow.bots.get_all()

        for bot in bots:
            # Считаем пользователей
            user_count = await uow.users.count(bot_id=bot.id, is_banned=False)

            # Считаем загрузки
            download_count = await uow.session.execute(
                select(func.count()).select_from(Download).where(Download.bot_id == bot.id)
            )
            downloads = download_count.scalar() or 0

            # Активные пользователи (за последние 30 дней)
            active_cutoff = datetime.now() - timedelta(days=30)
            active_count = await uow.session.execute(
                select(func.count()).select_from(User).where(
                    User.bot_id == bot.id,
                    User.updated_at >= active_cutoff,
                    User.is_banned == False,
                )
            )
            active = active_count.scalar() or 0

            await uow.bots.update(
                bot.id,
                total_users=user_count,
                active_users=active,
                total_downloads=downloads,
            )
            updated += 1

        await uow.commit()

    log.info("Bot stats updated", count=updated)
    return {"updated": updated}


async def aggregate_daily_stats(ctx: dict) -> dict[str, Any]:
    """Агрегация ежедневной статистики"""
    from sqlalchemy import select, func
    from src.models import Download, User, DailyStats, MediaSource

    log.info("Aggregating daily stats")

    today = datetime.now().date()
    yesterday = today - timedelta(days=1)

    async with UnitOfWork() as uow:
        # Для каждого бота и источника
        bots = await uow.bots.get_all()

        for bot in bots:
            for source in MediaSource:
                # Новые пользователи
                new_users = await uow.session.execute(
                    select(func.count()).select_from(User).where(
                        User.bot_id == bot.id,
                        func.date(User.created_at) == yesterday,
                    )
                )

                # Загрузки
                downloads = await uow.session.execute(
                    select(func.count()).select_from(Download).where(
                        Download.bot_id == bot.id,
                        Download.source == source,
                        func.date(Download.created_at) == yesterday,
                    )
                )

                # Сохраняем
                stats = DailyStats(
                    date=yesterday,
                    bot_id=bot.id,
                    source=source,
                    new_users=new_users.scalar() or 0,
                    downloads=downloads.scalar() or 0,
                )
                uow.session.add(stats)

        await uow.commit()

    log.info("Daily stats aggregated")
    return {"date": str(yesterday)}


# === Health Check ===

async def health_check(ctx: dict) -> dict[str, Any]:
    """Проверка здоровья системы"""
    status = {
        "time": datetime.now().isoformat(),
        "database": False,
        "redis": False,
        "bots": 0,
    }

    try:
        # Проверяем БД
        async with db.session() as session:
            await session.execute("SELECT 1")
            status["database"] = True
    except:
        pass

    try:
        # Проверяем Redis
        await cache.redis.ping()
        status["redis"] = True
    except:
        pass

    try:
        # Считаем активные боты
        bots = await bot_manager.get_all_active_bots()
        status["bots"] = len(bots)
    except:
        pass

    log.debug("Health check", **status)
    return status
