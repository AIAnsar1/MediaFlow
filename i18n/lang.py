"""
Message translations for the bot.
Structure: MESSAGES[key][language] = text
"""

MESSAGES = {
    "start": {
        "en": "👋 Hi! I'm a media downloader bot.\n\nSend me a link from any popular social network and I'll download the media for you!\n\n🎬 Supported: Instagram, TikTok, YouTube, Pinterest, VK",
        "ru": "👋 Привет! Я бот для скачивания медиа.\n\nОтправьте мне ссылку из любой популярной соцсети и я скачаю медиа для вас!\n\n🎬 Поддерживаю: Instagram, TikTok, YouTube, Pinterest, VK",
        "uz": "👋 Salom! Men media yuklab beruvchi botman.\n\nMenga mashhur ijtimoiy tarmoqlardan havola yuboring, men media yuklab beraman!\n\n🎬 Qo'llab-quvvatlayman: Instagram, TikTok, YouTube, Pinterest, VK",
    },
    "send_link": {
        "en": "🙌 Send a link to VK, YouTube, TikTok, Instagram or another social network.",
        "ru": "🙌 Отправляйте ссылку на VK, YouTube, TikTok, Instagram или другую соцсеть.",
        "uz": "🙌 VK, YouTube, TikTok, Instagram yoki boshqa ijtimoiy tarmoqdan havola yuboring.",
    },
    "unsupported_link": {
        "en": "❗ Supported links: Pinterest, VK, Youtube, YouTube Shorts, YouTube Playlists, TikTok, Instagram. From YouTube you can convert to Mp3 or Mp4. Please send a link from one of these platforms.",
        "ru": "❗ Поддерживаемые ссылки: Pinterest, VK, Youtube, YouTube Shorts, YouTube Playlists, TikTok, Instagram. С YouTube вы можете конвертировать в Mp3 или Mp4. Пожалуйста, отправьте ссылку из одной из этих соцсетей.",
        "uz": "❗ Qo'llab-quvvatlanadigan havolalar: Pinterest, VK, Youtube, YouTube Shorts, YouTube Playlists, TikTok, Instagram. YouTube'dan Mp3 yoki Mp4 ga aylantirishingiz mumkin.",
    },
    "error_processing": {
        "en": "❌ An error occurred while processing the link.",
        "ru": "❌ Произошла ошибка при обработке ссылки.",
        "uz": "❌ Havolani qayta ishlashda xatolik yuz berdi.",
    },
    "choose_download_type": {
        "en": "💁🏻‍♂️ What do you want to download?",
        "ru": "💁🏻‍♂️ Что вы хотите скачать?",
        "uz": "💁🏻‍♂️ Nima yuklab olmoqchisiz?",
    },
    "processing": {
        "en": "⏳ Processing... 🔄",
        "ru": "⏳ Обработка... 🔄",
        "uz": "⏳ Qayta ishlanmoqda... 🔄",
    },
    "no_formats_found": {
        "en": "❌ Could not get video formats.",
        "ru": "❌ Не удалось получить форматы видео.",
        "uz": "❌ Video formatlarini olib bo'lmadi.",
    },
    "check_size_video": {
        "en": "Select video quality 🎬:",
        "ru": "Выберите качество видео 🎬:",
        "uz": "Video sifatini tanlang 🎬:",
    },
    "start_download": {
        "en": "⏳ Starting download...",
        "ru": "⏳ Начинаю загрузку...",
        "uz": "⏳ Yuklash boshlanmoqda...",
    },
    "downloading_instagram": {
        "en": "🔎 Downloading media from Instagram...",
        "ru": "🔎 Скачиваю медиа с Instagram...",
        "uz": "🔎 Instagram'dan media yuklanmoqda...",
    },
    "downloading_tiktok": {
        "en": "🔎 Downloading media from TikTok...",
        "ru": "🔎 Скачиваю медиа с TikTok...",
        "uz": "🔎 TikTok'dan media yuklanmoqda...",
    },
    "downloading_pinterest": {
        "en": "🔎 Downloading media from Pinterest...",
        "ru": "🔎 Скачиваю медиа с Pinterest...",
        "uz": "🔎 Pinterest'dan media yuklanmoqda...",
    },
    "downloading_youtube": {
        "en": "⏬ Downloading from YouTube...",
        "ru": "⏬ Скачиваю с YouTube...",
        "uz": "⏬ YouTube'dan yuklanmoqda...",
    },
    "downloading_vk": {
        "en": "🔎 Downloading media from VK...",
        "ru": "🔎 Скачиваю медиа с VK...",
        "uz": "🔎 VK'dan media yuklanmoqda...",
    },
    "download_video": {
        "en": "🎬 Download Video",
        "ru": "🎬 Скачать Видео",
        "uz": "🎬 Video yuklab olish",
    },
    "download_audio": {
        "en": "🎵 Download Audio",
        "ru": "🎵 Скачать Аудио",
        "uz": "🎵 Audio yuklab olish",
    },
    "youtube_audio_downloaded": {
        "en": "✅ Audio downloaded",
        "ru": "✅ Аудио скачано",
        "uz": "✅ Audio yuklab olindi",
    },
    "no_media_found": {
        "en": "❌ Nothing found at the link.",
        "ru": "❌ Ничего не найдено по ссылке.",
        "uz": "❌ Havolada hech narsa topilmadi.",
    },
    "no_files_found": {
        "en": "❌ Error: no downloaded files found.",
        "ru": "❌ Ошибка: не найдено загруженных файлов.",
        "uz": "❌ Xatolik: yuklab olingan fayllar topilmadi.",
    },
    "file_too_large": {
        "en": "⚠️ File {filename} is too large to send via Telegram.",
        "ru": "⚠️ Файл {filename} слишком большой для отправки через Telegram.",
        "uz": "⚠️ {filename} fayli Telegram orqali yuborish uchun juda katta.",
    },
    "file_send_error": {
        "en": "❌ Error sending file: {filename}",
        "ru": "❌ Ошибка при отправке файла: {filename}",
        "uz": "❌ Faylni yuborishda xatolik: {filename}",
    },
    "all_files_sent": {
        "en": "✅ All files have been sent!",
        "ru": "✅ Все файлы отправлены!",
        "uz": "✅ Barcha fayllar yuborildi!",
    },
    "already_downloading": {
        "en": "💢 You already have an active download",
        "ru": "💢 У вас уже есть активная загрузка",
        "uz": "💢 Sizda allaqachon faol yuklab olish mavjud",
    },
    "in_queue": {
        "en": "🔄 Your download is in queue at position {}",
        "ru": "🔄 Ваша загрузка в очереди на позиции {}",
        "uz": "🔄 Yuklab olishingiz navbatda {} o'rinda",
    },
    "queue_full": {
        "en": "⌛️ The download queue is full. Please try again later.",
        "ru": "⌛️ Очередь загрузок заполнена. Пожалуйста, попробуйте позже.",
        "uz": "⌛️ Yuklab olish navbati to'ldi. Iltimos, keyinroq qayta urinib ko'ring.",
    },
    "queue_position": {
        "en": "🔄 Your request is in queue",
        "ru": "🔄 Ваш запрос добавлен в очередь",
        "uz": "🔄 So'rovingiz navbatga qo'shildi",
    },
    "queue_limit_reached": {
        "en": "You have reached the maximum number of active downloads.",
        "ru": "Вы достигли максимального количества активных загрузок.",
        "uz": "Siz maksimal faol yuklab olishlar soniga yetdingiz.",
    },
    "added_to_queue": {
        "en": "Added to download queue. Processing...",
        "ru": "Добавлено в очередь загрузки. Обработка...",
        "uz": "Yuklab olish navbatiga qo'shildi. Qayta ishlanmoqda...",
    },
    "queue_add_error": {
        "en": "Failed to add to download queue.",
        "ru": "Не удалось добавить в очередь загрузки.",
        "uz": "Yuklab olish navbatiga qo'shib bo'lmadi.",
    },
    "try_again": {
        "en": "🔄 Try Again",
        "ru": "🔄 Попробовать снова",
        "uz": "🔄 Qayta urinish",
    },
    "url_not_found": {
        "en": "🤷🏻 Link Not Found",
        "ru": "🤷🏻 Ссылка Не Найдена",
        "uz": "🤷🏻 Havola Topilmadi",
    },
    "lang_prompt": {
        "en": "🌍 Choose your language:",
        "ru": "🌍 Выберите язык:",
        "uz": "🌍 Tilni tanlang:",
    },
    "lang_changed": {
        "en": "✅ Language changed to English!",
        "ru": "✅ Язык изменён на русский!",
        "uz": "✅ Til o'zbek tiliga o'zgartirildi!",
    },
    "loading_youtube_info": {
        "en": "⏳ Getting video information...",
        "ru": "⏳ Загружаю информацию о видео...",
        "uz": "⏳ Video ma'lumotlari olinmoqda...",
    },
    "downloading_audio": {
        "en": "⏬ Downloading audio...",
        "ru": "⏬ Скачиваю аудио...",
        "uz": "⏬ Audio yuklanmoqda...",
    },
    "downloading_audio_mp3": {
        "en": "⏬ Downloading MP3 audio...",
        "ru": "⏬ Скачиваю аудио MP3...",
        "uz": "⏬ MP3 audio yuklanmoqda...",
    },
    "your_media_from": {
        "en": "🎥 Your video from {}",
        "ru": "🎥 Ваше Видео из {}",
        "uz": "🎥 {} dan sizning videongiz",
    },
}


def get_message(key: str, lang: str = "en", **kwargs) -> str:
    """Get a message by key and language, fallback to Russian then English."""
    messages = MESSAGES.get(key, {})
    # Priority: requested lang -> Russian -> English -> key itself
    return messages.get(lang) or messages.get("ru") or messages.get("en", key)
