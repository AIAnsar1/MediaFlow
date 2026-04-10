from uuid import UUID

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from services.cache_channel import (
    CacheChannelService,
    CreateCacheChannelDTO,
    UpdateCacheChannelDTO,
    CacheChannelAlreadyExistsError,
    CacheChannelNotFoundError,
    NoCacheChannelAvailableError,
)
from database import get_session
from app.logging import get_logger

log = get_logger("controller.cache_channel")

router = Router(name="cache_channel")


# ================================================================
# FSM States
# ================================================================

class AddChannelStates(StatesGroup):
    waiting_name = State()
    waiting_telegram_id = State()
    waiting_username = State()
    waiting_description = State()


# ================================================================
# Filters (простая проверка прав, замените на свою)
# ================================================================

# Вынесите ID админов в конфиг
ADMIN_IDS: list[int] = []  # TODO: заполнить из settings


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ================================================================
# /cache_channel list
# ================================================================

@router.message(Command("cache_channels"))
async def cmd_list_channels(message: Message) -> None:
    """Показать список всех кэш-каналов."""
    if not is_admin(message.from_user.id):  # type: ignore[union-attr]
        return

    async with get_session() as session:
        service = CacheChannelService(session)
        channels = await service.list_all()

    if not channels:
        await message.answer("📭 Кэш-каналы не добавлены.")
        return

    lines = ["📋 <b>Кэш-каналы:</b>\n"]
    for ch in channels:
        status = "✅" if ch.is_active else "❌"
        username_str = f"@{ch.username}" if ch.username else "без username"
        lines.append(
            f"{status} <b>{ch.name}</b>\n"
            f"   ID: <code>{ch.telegram_id}</code>\n"
            f"   Username: {username_str}\n"
            f"   UUID: <code>{ch.id}</code>\n"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


# ================================================================
# /cache_channel add — FSM
# ================================================================

@router.message(Command("add_cache_channel"))
async def cmd_add_channel_start(message: Message, state: FSMContext) -> None:
    """Начать добавление нового кэш-канала."""
    if not is_admin(message.from_user.id):  # type: ignore[union-attr]
        return

    await message.answer(
        "📝 Введите <b>название</b> канала (например: YouTube Cache):",
        parse_mode="HTML",
    )
    await state.set_state(AddChannelStates.waiting_name)


@router.message(AddChannelStates.waiting_name)
async def fsm_add_channel_name(message: Message, state: FSMContext) -> None:
    """Принять название канала."""
    name = (message.text or "").strip()

    if len(name) < 2:
        await message.answer("❗ Название слишком короткое. Введите ещё раз:")
        return

    await state.update_data(name=name)
    await message.answer(
        "🔢 Введите <b>Telegram ID</b> канала (отрицательное число, например: -1001234567890):",
        parse_mode="HTML",
    )
    await state.set_state(AddChannelStates.waiting_telegram_id)


@router.message(AddChannelStates.waiting_telegram_id)
async def fsm_add_channel_telegram_id(message: Message, state: FSMContext) -> None:
    """Принять Telegram ID канала."""
    raw = (message.text or "").strip()

    try:
        telegram_id = int(raw)
    except ValueError:
        await message.answer("❗ Введите корректный числовой ID (например: -1001234567890):")
        return

    # Telegram ID каналов всегда отрицательный
    if telegram_id > 0:
        await message.answer(
            "⚠️ ID канала должен быть отрицательным числом. Попробуйте ещё раз:"
        )
        return

    await state.update_data(telegram_id=telegram_id)
    await message.answer(
        "👤 Введите <b>username</b> канала (без @) или <b>-</b> если канал без username:",
        parse_mode="HTML",
    )
    await state.set_state(AddChannelStates.waiting_username)


@router.message(AddChannelStates.waiting_username)
async def fsm_add_channel_username(message: Message, state: FSMContext) -> None:
    """Принять username канала."""
    raw = (message.text or "").strip()
    username = None if raw == "-" else raw.lstrip("@")

    await state.update_data(username=username)
    await message.answer(
        "📄 Введите <b>описание</b> канала или <b>-</b> чтобы пропустить:",
        parse_mode="HTML",
    )
    await state.set_state(AddChannelStates.waiting_description)


@router.message(AddChannelStates.waiting_description)
async def fsm_add_channel_description(message: Message, state: FSMContext) -> None:
    """Принять описание и создать канал."""
    raw = (message.text or "").strip()
    description = None if raw == "-" else raw

    data = await state.get_data()
    await state.clear()

    dto = CreateCacheChannelDTO(
        name=data["name"],
        telegram_id=data["telegram_id"],
        username=data.get("username"),
        description=description,
    )

    try:
        async with get_session() as session:
            service = CacheChannelService(session)
            channel = await service.create(dto)
            await session.commit()

    except CacheChannelAlreadyExistsError as e:
        await message.answer(f"❌ Ошибка: {e}")
        return

    username_str = f"@{channel.username}" if channel.username else "без username"
    await message.answer(
        f"✅ <b>Канал добавлен!</b>\n\n"
        f"📛 Название: {channel.name}\n"
        f"🆔 Telegram ID: <code>{channel.telegram_id}</code>\n"
        f"👤 Username: {username_str}\n"
        f"🔑 UUID: <code>{channel.id}</code>",
        parse_mode="HTML",
    )
    log.info("Cache channel added via bot", telegram_id=channel.telegram_id)


# ================================================================
# /delete_cache_channel <telegram_id>
# ================================================================

@router.message(Command("delete_cache_channel"))
async def cmd_delete_channel(message: Message) -> None:
    """
    Удалить кэш-канал.
    Использование: /delete_cache_channel -1001234567890
    """
    if not is_admin(message.from_user.id):  # type: ignore[union-attr]
        return

    args = (message.text or "").split()
    if len(args) < 2:
        await message.answer("❗ Использование: /delete_cache_channel <telegram_id>")
        return

    try:
        telegram_id = int(args[1])
    except ValueError:
        await message.answer("❗ Telegram ID должен быть числом.")
        return

    try:
        async with get_session() as session:
            service = CacheChannelService(session)
            await service.delete_by_telegram_id(telegram_id)
            await session.commit()

        await message.answer(f"🗑️ Канал <code>{telegram_id}</code> удалён.", parse_mode="HTML")

    except CacheChannelNotFoundError:
        await message.answer(f"❌ Канал с ID <code>{telegram_id}</code> не найден.", parse_mode="HTML")


# ================================================================
# /toggle_cache_channel <uuid>
# ================================================================

@router.message(Command("toggle_cache_channel"))
async def cmd_toggle_channel(message: Message) -> None:
    """
    Переключить активность канала.
    Использование: /toggle_cache_channel <uuid>
    """
    if not is_admin(message.from_user.id):  # type: ignore[union-attr]
        return

    args = (message.text or "").split()
    if len(args) < 2:
        await message.answer("❗ Использование: /toggle_cache_channel <uuid>")
        return

    try:
        channel_id = UUID(args[1])
    except ValueError:
        await message.answer("❗ Неверный формат UUID.")
        return

    try:
        async with get_session() as session:
            service = CacheChannelService(session)
            channel = await service.toggle_active(channel_id)
            await session.commit()

        status = "✅ активирован" if channel.is_active else "❌ деактивирован"
        await message.answer(
            f"🔄 Канал <b>{channel.name}</b> {status}.",
            parse_mode="HTML",
        )

    except CacheChannelNotFoundError:
        await message.answer(f"❌ Канал не найден.")