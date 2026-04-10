import asyncio
import time
from typing import Any

from litestar import Controller, get, post
from litestar.background_tasks import BackgroundTask
from litestar.response import Response
from litestar.status_codes import HTTP_200_OK, HTTP_401_UNAUTHORIZED, HTTP_503_SERVICE_UNAVAILABLE
from litestar.exceptions import HTTPException

from app.logging import get_logger
from bot.processor import update_processor
from services import bot_manager

log = get_logger("webhook")


class WebhookController(Controller):
    path = "/webhook"

    @get("/health", name="webhook:health")
    async def health_check(self) -> Response:
        """Health check endpoint"""
        try:
            instances_count = len(bot_manager._instances) if hasattr(bot_manager, "_instances") else 0
            return Response(
                content={
                    "status": "ok",
                    "bots_loaded": instances_count,
                },
                status_code=HTTP_200_OK,
            )
        except Exception as e:
            log.error("Health check failed", error=str(e))
            return Response(
                content={"status": "error", "detail": str(e)},
                status_code=HTTP_503_SERVICE_UNAVAILABLE,
            )

    @post("/{bot_token:str}", name="webhook:handle")
    async def handle_webhook(
        self,
        bot_token: str,
        data: dict[str, Any],
    ) -> Response:
        """
        Handle incoming Telegram webhook updates.
        Returns 200 OK IMMEDIATELY, processes in background.
        """
        # ✅ ОТВЕЧАЕМ 200 МГНОВЕННО — без всяких await!
        # Вся обработка в background чтобы Telegram не закрыл соединение

        # ✅ BackgroundTask — запускается ПОСЛЕ отправки ответа
        background = BackgroundTask(
            _process_in_background,
            bot_token=bot_token,
            data=data,
        )

        return Response(
            content={"ok": True},
            status_code=HTTP_200_OK,
            background=background,
        )


async def _process_in_background(bot_token: str, data: dict[str, Any]) -> None:
    """Process webhook update in background"""
    update_id = data.get("update_id")
    update_type = _detect_update_type(data)
    start_time = time.monotonic()

    log.info(
        "⚙️ Processing update",
        token=bot_token[:10],
        update_id=update_id,
        update_type=update_type,
    )

    try:
        await update_processor.process(bot_token, data)

        elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)
        log.info(
            "Update processed",
            update_id=update_id,
            update_type=update_type,
            elapsed_ms=elapsed_ms,
        )

    except asyncio.CancelledError:
        # Важно! Не глотать CancelledError
        log.warning("Update processing cancelled", update_id=update_id)
        raise

    except Exception as e:
        elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)
        log.exception(
            "Background processing error",
            update_id=update_id,
            update_type=update_type,
            elapsed_ms=elapsed_ms,
            error=str(e),
            error_type=type(e).__name__,
        )


def _detect_update_type(data: dict[str, Any]) -> str:
    """Определяем тип апдейта для логов"""
    update_types = (
        "message",
        "edited_message",
        "channel_post",
        "callback_query",
        "inline_query",
        "chosen_inline_result",
        "shipping_query",
        "pre_checkout_query",
        "poll",
        "poll_answer",
        "my_chat_member",
        "chat_member",
    )
    for update_type in update_types:
        if update_type in data:
            return update_type
    return "unknown"
