from litestar import Controller, post
from litestar.response import Response
from litestar.status_codes import HTTP_200_OK

from src.logging import get_logger
from src.bot.processor import update_processor

log = get_logger("webhook")


class WebhookController(Controller):
    path = "/webhook"

    @post("/{bot_token:str}", name="webhook:handle")
    async def handle_webhook(
        self,
        bot_token: str,
        data: dict,
    ) -> Response:
        """
        Handle incoming Telegram webhook updates

        Telegram sends POST request with JSON body containing Update
        """
        log.debug("Received webhook", token=bot_token[:10], update_id=data.get("update_id"))

        try:
            # Обрабатываем update
            await update_processor.process(bot_token, data)
        except Exception as e:
            log.exception("Webhook processing error", error=str(e))

        # Всегда возвращаем 200 OK чтобы Telegram не ретраил
        return Response(
            content={"ok": True},
            status_code=HTTP_200_OK,
        )
