from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_language_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора языка"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_language:ru"),
            InlineKeyboardButton(text="🇺🇸 English", callback_data="set_language:en"),
        ]
    ])


def get_youtube_choice_keyboard(video_id: str, language: str = "en") -> InlineKeyboardMarkup:
    """Клавиатура video/audio для YouTube"""
    if language == "ru":
        video_text = "🎬 Видео"
        audio_text = "🎵 Аудио (MP3)"
    else:
        video_text = "🎬 Video"
        audio_text = "🎵 Audio (MP3)"

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=video_text,
                callback_data=f"yt_download:video:{video_id}",
            ),
            InlineKeyboardButton(
                text=audio_text,
                callback_data=f"yt_download:audio:{video_id}",
            ),
        ]
    ])


def get_youtube_formats_keyboard(
    formats: list[dict],
    url: str,
) -> InlineKeyboardMarkup:
    """
    Клавиатура с форматами YouTube

    formats: [{"format_id": "...", "quality": "720p", "filesize_str": "10.5 MB"}, ...]
    """
    buttons = []

    for fmt in formats:
        quality = fmt.get("quality", fmt.get("resolution", ""))
        format_id = fmt.get("format_id", "")
        size_str = fmt.get("filesize_str", fmt.get("size_str", ""))

        # Формируем текст кнопки
        if size_str:
            button_text = f"🎬 {quality} | 💾 {size_str}"
        else:
            button_text = f"🎬 {quality}"

        buttons.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"yt_format:{format_id}:{url[:50]}",  # Ограничиваем URL
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_youtube_formats_keyboard_v2(
    formats: list[dict],
    video_id: str,
) -> InlineKeyboardMarkup:
    """
    Альтернативная версия - передаём video_id вместо полного URL
    """
    buttons = []

    for fmt in formats:
        quality = fmt.get("quality", "")
        format_id = fmt.get("format_id", "")
        size_str = fmt.get("filesize_str", "")

        if size_str:
            button_text = f"🎬 {quality} | 💾 {size_str}"
        else:
            button_text = f"🎬 {quality}"

        # Используем video_id вместо полного URL
        buttons.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"yt_fmt:{format_id}:{video_id}",
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_cancel_keyboard(language: str = "en") -> InlineKeyboardMarkup:
    """Клавиатура отмены"""
    text = "❌ Отмена" if language == "ru" else "❌ Cancel"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data="cancel")]
    ])
