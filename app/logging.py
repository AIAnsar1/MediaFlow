import sys
from pathlib import Path
from typing import Any
from loguru import logger
from functools import lru_cache

from app.config import settings


class LoggerManager:
    """

    Возможности:
    - Цветной вывод в консоль
    - Ротация файлов по дате и размеру
    - Отдельные файлы для ошибок
    - Контекстные логгеры для разных модулей
    - JSON формат для production
    - Фильтрация по уровням
    """

    _initialized: bool = False
    _log_dir: Path = Path("storage/logs")

    # Форматы
    CONSOLE_FORMAT = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{extra[name]}</cyan> | "
        "<level>{message}</level>"
    )

    FILE_FORMAT = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
        "{level: <8} | "
        "{extra[name]} | "
        "{name}:{function}:{line} | "
        "{message}"
    )

    JSON_FORMAT = (
        '{{"time":"{time:YYYY-MM-DDTHH:mm:ss.SSSZ}",'
        '"level":"{level}",'
        '"module":"{extra[name]}",'
        '"location":"{name}:{function}:{line}",'
        '"message":"{message}"}}'
    )

    @classmethod
    def setup(cls, log_dir: str | Path = "storage/logs") -> None:
        """Инициализация логгера (вызывать один раз при старте)"""
        if cls._initialized:
            return

        cls._log_dir = Path(log_dir)
        cls._log_dir.mkdir(parents=True, exist_ok=True)

        # Удаляем дефолтный handler
        logger.remove()

        # Определяем уровень логирования
        log_level = "DEBUG" if settings.debug else "INFO"

        # === Console Handler ===
        logger.add(
            sys.stderr,
            format=cls.CONSOLE_FORMAT,
            level=log_level,
            colorize=True,
            filter=lambda record: record["extra"].get("name", "app"),
        )

        # === Main Log File (all levels) ===
        logger.add(
            cls._log_dir / "app_{time:YYYY-MM-DD}.log",
            format=cls.FILE_FORMAT,
            level="DEBUG",
            rotation="00:00",  # Новый файл каждый день
            retention="30 days",  # Хранить 30 дней
            compression="zip",  # Сжимать старые
            encoding="utf-8",
            enqueue=True,  # Асинхронная запись
        )

        # === Error Log File ===
        logger.add(
            cls._log_dir / "errors_{time:YYYY-MM-DD}.log",
            format=cls.FILE_FORMAT,
            level="ERROR",
            rotation="00:00",
            retention="90 days",
            compression="zip",
            encoding="utf-8",
            enqueue=True,
            backtrace=True,  # Полный traceback
            diagnose=True,  # Детальная диагностика
        )

        # === SQL Log File (для отладки запросов) ===
        logger.add(
            cls._log_dir / "sql_{time:YYYY-MM-DD}.log",
            format=cls.FILE_FORMAT,
            level="DEBUG",
            rotation="00:00",
            retention="7 days",
            compression="zip",
            encoding="utf-8",
            enqueue=True,
            filter=lambda record: record["extra"].get("name") == "database",
        )

        # === Bot Log File ===
        logger.add(
            cls._log_dir / "bot_{time:YYYY-MM-DD}.log",
            format=cls.FILE_FORMAT,
            level="DEBUG",
            rotation="00:00",
            retention="14 days",
            compression="zip",
            encoding="utf-8",
            enqueue=True,
            filter=lambda record: record["extra"].get("name", "").startswith("bot"),
        )

        # === JSON Log (для production / ELK) ===
        if not settings.debug:
            logger.add(
                cls._log_dir / "app_{time:YYYY-MM-DD}.json",
                format=cls.JSON_FORMAT,
                level="INFO",
                rotation="100 MB",
                retention="14 days",
                compression="zip",
                encoding="utf-8",
                enqueue=True,
                serialize=False,
            )

        cls._initialized = True

        # Логируем старт
        app_logger = cls.get_logger("app")
        app_logger.info(f"Logger initialized | Level: {log_level} | Path: {cls._log_dir}")

    @classmethod
    def get_logger(cls, name: str = "app") -> "BoundLogger":
        if not cls._initialized:
            cls.setup()
        return BoundLogger(name)

    @classmethod
    def shutdown(cls) -> None:
        """Корректное завершение логгера"""
        logger.info("Shutting down logger...")
        logger.complete()  # Дождаться записи всех логов


class BoundLogger:
    """
    Использование:
        log = LoggerManager.get_logger("bot.handlers")
        log.info("User started bot", user_id=123)
        log.error("Download failed", url=url, error=str(e))
    """

    def __init__(self, name: str):
        self.name = name
        self._logger = logger.bind(name=name)

    def debug(self, message: str, **kwargs: Any) -> None:
        self._logger.opt(depth=1).debug(self._format_message(message, kwargs))

    def info(self, message: str, **kwargs: Any) -> None:
        self._logger.opt(depth=1).info(self._format_message(message, kwargs))

    def warning(self, message: str, **kwargs: Any) -> None:
        self._logger.opt(depth=1).warning(self._format_message(message, kwargs))

    def error(self, message: str, **kwargs: Any) -> None:
        self._logger.opt(depth=1).error(self._format_message(message, kwargs))

    def critical(self, message: str, **kwargs: Any) -> None:
        self._logger.opt(depth=1).critical(self._format_message(message, kwargs))

    def exception(self, message: str, **kwargs: Any) -> None:
        self._logger.opt(depth=1, exception=True).error(self._format_message(message, kwargs))

    def success(self, message: str, **kwargs: Any) -> None:
        """Кастомный уровень SUCCESS (зелёный)"""
        self._logger.opt(depth=1).success(self._format_message(message, kwargs))

    @staticmethod
    def _format_message(message: str, kwargs: dict) -> str:
        if not kwargs:
            return message
        extra = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        return f"{message} | {extra}"

    def bind(self, **kwargs: Any) -> "BoundLogger":
        new_logger = BoundLogger(self.name)
        new_logger._logger = self._logger.bind(**kwargs)
        return new_logger


# === Shortcut функции ===

@lru_cache(maxsize=32)
def get_logger(name: str = "app") -> BoundLogger:
    """Кешированный getter для логгера"""
    return LoggerManager.get_logger(name)


def setup_logging(log_dir: str = "storage/logs") -> None:
    """Инициализация логирования"""
    LoggerManager.setup(log_dir)
