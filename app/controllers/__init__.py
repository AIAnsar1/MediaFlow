from src.web.controllers.admin import AdminController
from src.web.controllers.auth import AuthController
from src.web.controllers.bots import BotController
from src.web.controllers.ads import AdController
from src.web.controllers.stats import StatsController
from src.web.controllers.queues import QueueController
from src.web.controllers.webhook import WebhookController
from src.web.controllers.health import HealthController
from src.web.controllers.index import IndexController
from src.web.controllers.users import UserController

__all__ = [
    "AdminController",
    "AuthController",
    "BotController",
    "AdController",
    "StatsController",
    "QueueController",
    "WebhookController",
    "HealthController",
    "IndexController",
    "UserController",
]
