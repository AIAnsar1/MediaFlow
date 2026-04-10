from litestar import Controller, get
from litestar.response import Redirect, Response
from litestar.status_codes import HTTP_204_NO_CONTENT


class IndexController(Controller):
    path = "/"

    @get("/", name="index")
    async def index(self) -> Redirect:
        """Redirect root to admin dashboard"""
        return Redirect(path="/admin")

    @get("/favicon.ico", status_code=200, name="favicon")
    async def favicon(self) -> Response:
        return Response(content=b"", media_type="image/x-icon")
