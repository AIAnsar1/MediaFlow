from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base


class Language(Base):
    __tablename__ = "languages"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)  # en, ru, uk
    name: Mapped[str] = mapped_column(String(64))  # English, Русский
    translations: Mapped[str] = mapped_column(Text)  # JSON string with all translations
    is_default: Mapped[bool] = mapped_column(default=False)
