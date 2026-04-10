from litestar import Controller, get, post, put, delete
from litestar.response import Template, Redirect
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.di import Provide
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import Bot as AiogramBot
import re

from database.connection import get_session
from repositories import BotRepository
from models import BotStatus


class BotController(Controller):
    path = "/admin/bots"
    dependencies = {"session": Provide(get_session)}

    @get("/", name="bots:list")
    async def list_bots(self, session: AsyncSession) -> Template:
        repo = BotRepository(session)
        bots = await repo.get_all(order_by="created_at")
        return Template(
            template_name="admin/bots/list.html",
            context={"bots": bots}
        )

    @get("/create", name="bots:create_form")
    async def create_form(self) -> Template:
        return Template(template_name="admin/bots/create.html")

    @post("/create", name="bots:create")
    async def create_bot(
        self,
        session: AsyncSession,
        data: dict = Body(media_type=RequestEncodingType.URL_ENCODED),
    ) -> Redirect:
        repo = BotRepository(session)

        token = data.get("token", "").strip()
        name = data.get("name", "").strip()
        description = data.get("description", "").strip() or None
        status = data.get("status", BotStatus.ACTIVE)
        is_webhook = data.get("is_webhook") == "true"
        webhook_url = data.get("webhook_url", "").strip() or None
        webhook_secret = data.get("webhook_secret", "").strip() or None

        # Validate webhook secret (Telegram only allows A-Z, a-z, 0-9, -, _)
        if webhook_secret and not re.match(r'^[A-Za-z0-9_-]+$', webhook_secret):
            return Redirect(path="/admin/bots/create?error=Webhook secret can only contain letters, numbers, hyphens and underscores")
        if webhook_secret and len(webhook_secret) > 256:
            return Redirect(path="/admin/bots/create?error=Webhook secret must be 256 characters or less")

        # Validate token with Telegram
        try:
            aiogram_bot = AiogramBot(token=token)
            bot_info = await aiogram_bot.get_me()
            await aiogram_bot.session.close()
        except Exception as e:
            return Redirect(path=f"/admin/bots/create?error=Invalid token: {e}")

        # Check if already exists
        existing = await repo.get_by_bot_id(bot_info.id)
        if existing:
            return Redirect(path="/admin/bots/create?error=Bot already registered")

        # Create bot
        await repo.create(
            token=token,
            bot_id=bot_info.id,
            username=bot_info.username,
            name=name or bot_info.first_name,
            description=description,
            status=status,
            is_webhook=is_webhook,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
        )

        return Redirect(path="/admin/bots?message=Bot registered successfully")

    @get("/{bot_id:int}", name="bots:detail")
    async def bot_detail(self, session: AsyncSession, bot_id: int) -> Template:
        repo = BotRepository(session)
        bot = await repo.get_by_id(bot_id)
        if not bot:
            return Redirect(path="/admin/bots")

        return Template(
            template_name="admin/bots/detail.html",
            context={"bot": bot}
        )

    @post("/{bot_id:int}/toggle", name="bots:toggle")
    async def toggle_bot(self, session: AsyncSession, bot_id: int) -> Redirect:
        repo = BotRepository(session)
        bot = await repo.get_by_id(bot_id)
        if bot:
            new_status = BotStatus.INACTIVE if bot.status == BotStatus.ACTIVE else BotStatus.ACTIVE
            await repo.update(bot_id, status=new_status)
        return Redirect(path="/admin/bots")

    @post("/{bot_id:int}/delete", name="bots:delete")
    async def delete_bot(self, session: AsyncSession, bot_id: int) -> Redirect:
        repo = BotRepository(session)
        await repo.delete(bot_id)
        return Redirect(path="/admin/bots")
