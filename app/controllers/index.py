from litestar import Controller, get
from litestar.response import Redirect


class IndexController(Controller):
    path = "/"

    @get("/", name="index")
    async def index(self) -> Redirect:
        """Redirect root to admin dashboard"""
        return Redirect(path="/admin")
