from litestar import Controller, get
from litestar.response import Redirect, Response
from litestar.status_codes import HTTP_204_NO_CONTENT


class IndexController(Controller):
    path = "/"

    @get("/", name="index")
    async def index(self) -> Redirect:
        """Redirect root to admin dashboard"""
        return Redirect(path="/admin")

    @get("/favicon.ico", status_code=HTTP_204_NO_CONTENT, name="favicon")
    async def favicon(self) -> Response:
        """Empty response for favicon to avoid 404 errors in logs"""
        return Response(content=b"")
