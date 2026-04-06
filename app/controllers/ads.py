from litestar import Controller, get, post
from litestar.response import Template, Redirect
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.di import Provide
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from repositories import AdRepository, BotRepository, UserRepository
from models import AdStatus, AdMediaType


class AdController(Controller):
    path = "/admin/ads"
    dependencies = {"session": Provide(get_session)}

    @get("/", name="ads:list")
    async def list_ads(
        self,
        session: AsyncSession,
        page: int = 1,
        per_page: int = 10
    ) -> Template:
        repo = AdRepository(session)
        offset = (page - 1) * per_page
        ads = await repo.get_all(offset=offset, limit=per_page, order_by="created_at")
        total = await repo.count()

        return Template(
            template_name="admin/ads/list.html",
            context={
                "ads": ads,
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": (total + per_page - 1) // per_page
            }
        )

    @get("/create", name="ads:create_form")
    async def create_form(self, session: AsyncSession) -> Template:
        bot_repo = BotRepository(session)
        bots = await bot_repo.get_active_bots()
        return Template(
            template_name="admin/ads/create.html",
            context={"bots": bots, "languages": ["ru", "en", "uk"]}
        )

    @post("/create", name="ads:create")
    async def create_ad(
        self,
        session: AsyncSession,
        data: dict = Body(media_type=RequestEncodingType.URL_ENCODED),
    ) -> Redirect:
        ad_repo = AdRepository(session)

        name = data.get("name", "").strip()
        content = data.get("content", "").strip()
        button_text = data.get("button_text", "").strip() or None
        button_url = data.get("button_url", "").strip() or None
        target_language = data.get("target_language") or None
        bot_ids = data.getlist("bot_ids") if hasattr(data, 'getlist') else [data.get("bot_ids")]
        bot_ids = [int(bid) for bid in bot_ids if bid]

        if not name or not content or not bot_ids:
            return Redirect(path="/admin/ads/create?error=Missing required fields")

        # Create ad
        ad = await ad_repo.create(
            name=name,
            content=content,
            media_type=AdMediaType.NONE,  # TODO: Handle media upload
            button_text=button_text,
            button_url=button_url,
            target_language=target_language,
            status=AdStatus.DRAFT,
        )

        # Add target bots
        await ad_repo.add_target_bots(ad.id, bot_ids)

        return Redirect(path=f"/admin/ads/{ad.id}")

    @get("/{ad_id:int}", name="ads:detail")
    async def ad_detail(self, session: AsyncSession, ad_id: int) -> Template:
        repo = AdRepository(session)
        ad = await repo.get_with_relations(ad_id)
        if not ad:
            return Redirect(path="/admin/ads")

        return Template(
            template_name="admin/ads/detail.html",
            context={"ad": ad}
        )

    @post("/{ad_id:int}/send", name="ads:send")
    async def send_ad(self, session: AsyncSession, ad_id: int) -> Redirect:
        """Queue ad for background sending"""
        from services import queue_service

        ad_repo = AdRepository(session)
        ad = await ad_repo.get_with_relations(ad_id)

        if not ad:
            return Redirect(path="/admin/ads")

        # Добавляем в очередь ARQ
        job_id = await queue_service.enqueue_broadcast(ad_id)

        if job_id:
            await ad_repo.update(ad_id, status=AdStatus.SCHEDULED)
            return Redirect(path=f"/admin/ads/{ad_id}?status=queued&job={job_id}")
        else:
            return Redirect(path=f"/admin/ads/{ad_id}?error=queue_failed")


    @post("/{ad_id:int}/delete-with-messages", name="ads:delete_with_messages")
    async def delete_with_messages(self, session: AsyncSession, ad_id: int) -> Redirect:
        """Delete ad and all sent messages"""
        from services import queue_service

        job_id = await queue_service.enqueue_delete_ad(ad_id)

        if job_id:
            return Redirect(path=f"/admin/ads?status=deleting&job={job_id}")
        else:
            return Redirect(path=f"/admin/ads/{ad_id}?error=delete_failed")

    @post("/{ad_id:int}/delete", name="ads:delete")
    async def delete_ad(self, session: AsyncSession, ad_id: int) -> Redirect:
        repo = AdRepository(session)
        await repo.delete(ad_id)
        return Redirect(path="/admin/ads")
