from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_language_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора языка"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_language:ru"),
            InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="set_language:uz"),
            InlineKeyboardButton(text="🇺🇸 English", callback_data="set_language:en"),
        ]
    ])





def get_youtube_formats_keyboard_v2(
    formats: list[dict],
    video_id: str,
    cache_status: dict | None = None,
) -> InlineKeyboardMarkup:
    """
    Клавиатура с форматами + аудио кнопка
    formats: [{"format_id": "...", "quality": "720p", "filesize_str": "10.5 MB"}, ...]
    cache_status: {"360p": True, "720p": True, ...} — какие качества уже в кеше
    """
    buttons = []
    cache_status = cache_status or {}

    # Видео форматы
    for fmt in formats:
        quality = fmt.get("quality", "")
        format_id = fmt.get("format_id", "")
        size_str = fmt.get("filesize_str", "")

        # Определяем эмодзи: ⚡️ если в кеше, 💢 если нет
        emoji = "⚡️" if cache_status.get(quality) else "💢"

        if size_str:
            button_text = f"{emoji} 📹 {quality} - 💾 {size_str}"
        else:
            button_text = f"{emoji} 📹 {quality}"

        buttons.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"yt_fmt:{format_id}:{quality}:{video_id}",
            )
        ])

    # Кнопка аудио
    audio_size = formats[0].get("audio_size_str", "") if formats else ""
    audio_in_cache = cache_status.get("audio")
    audio_emoji = "⚡️" if audio_in_cache else "💢"

    if audio_size:
        audio_text = f"{audio_emoji} 🔊 Audio - 💾 {audio_size}"
    else:
        audio_text = f"{audio_emoji} 🔊 Audio (MP3)"

    buttons.append([
        InlineKeyboardButton(
            text=audio_text,
            callback_data=f"yt_audio:{video_id}",
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_cancel_keyboard(language: str = "en") -> InlineKeyboardMarkup:
    """Клавиатура отмены"""
    text = "❌ Отмена" if language == "ru" else "❌ Cancel"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data="cancel")]
    ])
