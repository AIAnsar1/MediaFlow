from typing import TypeVar, Generic, Sequence, Any
from sqlalchemy import select, update, delete, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.sql import Select

from models.base import Base
from app.logging import get_logger

ModelType = TypeVar("ModelType", bound=Base)

log = get_logger("repository")


class BaseRepository(Generic[ModelType]):
    """
    Базовый репозиторий с CRUD операциями

    Использование:
        class UserRepository(BaseRepository[User]):
            model = User

            async def get_active_users(self):
                return await self.filter(is_active=True)
    """

    model: type[ModelType]

    def __init__(self, session: AsyncSession):
        self.session = session
        self._log = get_logger(f"repository.{self.model.__name__.lower()}")

    # === CREATE ===

    async def create(self, **kwargs: Any) -> ModelType:
        """Создать запись"""
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        self._log.debug("Created", id=instance.id)
        return instance

    async def create_many(self, items: list[dict[str, Any]]) -> list[ModelType]:
        """Создать несколько записей"""
        instances = [self.model(**item) for item in items]
        self.session.add_all(instances)
        await self.session.flush()
        for instance in instances:
            await self.session.refresh(instance)
        self._log.debug("Created many", count=len(instances))
        return instances

    # === READ ===

    async def get_by_id(self, id: int) -> ModelType | None:
        """Получить по ID"""
        return await self.session.get(self.model, id)

    async def get_by_ids(self, ids: list[int]) -> Sequence[ModelType]:
        """Получить несколько по ID"""
        stmt = select(self.model).where(self.model.id.in_(ids))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_one(self, **filters: Any) -> ModelType | None:
        """Получить одну запись по фильтрам"""
        stmt = self._apply_filters(select(self.model), filters)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        offset: int = 0,
        limit: int = 100,
        order_by: str | None = None,
        desc: bool = True,
        **filters: Any,
    ) -> Sequence[ModelType]:
        """Получить все с пагинацией и фильтрами"""
        stmt = self._apply_filters(select(self.model), filters)
        stmt = self._apply_ordering(stmt, order_by, desc)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def filter(
        self,
        offset: int = 0,
        limit: int = 100,
        order_by: str | None = "created_at",
        desc: bool = True,
        **filters: Any,
    ) -> Sequence[ModelType]:
        """Алиас для get_all с фильтрами"""
        return await self.get_all(
            offset=offset,
            limit=limit,
            order_by=order_by,
            desc=desc,
            **filters,
        )

    async def count(self, **filters: Any) -> int:
        """Подсчёт записей"""
        stmt = select(func.count()).select_from(self.model)
        stmt = self._apply_filters(stmt, filters)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def exists(self, **filters: Any) -> bool:
        """Проверка существования"""
        count = await self.count(**filters)
        return count > 0

    # === UPDATE ===

    async def update(self, id: int, **kwargs: Any) -> ModelType | None:
        """Обновить по ID"""
        instance = await self.get_by_id(id)
        if instance is None:
            return None

        for key, value in kwargs.items():
            if hasattr(instance, key):
                setattr(instance, key, value)

        await self.session.flush()
        await self.session.refresh(instance)
        self._log.debug("Updated", id=id)
        return instance

    async def update_many(self, filters: dict[str, Any], **kwargs: Any) -> int:
        """Обновить несколько записей по фильтру"""
        stmt = update(self.model).values(**kwargs)
        stmt = self._apply_filters(stmt, filters)
        result = await self.session.execute(stmt)
        self._log.debug("Updated many", count=result.rowcount)
        return result.rowcount

    async def upsert(self, lookup: dict[str, Any], defaults: dict[str, Any]) -> tuple[ModelType, bool]:
        """
        Создать или обновить
        Returns: (instance, created: bool)
        """
        instance = await self.get_one(**lookup)
        if instance:
            for key, value in defaults.items():
                setattr(instance, key, value)
            await self.session.flush()
            return instance, False
        else:
            instance = await self.create(**lookup, **defaults)
            return instance, True

    # === DELETE ===

    async def delete(self, id: int) -> bool:
        """Удалить по ID"""
        stmt = delete(self.model).where(self.model.id == id)
        result = await self.session.execute(stmt)
        deleted = result.rowcount > 0
        if deleted:
            self._log.debug("Deleted", id=id)
        return deleted

    async def delete_many(self, **filters: Any) -> int:
        """Удалить несколько по фильтру"""
        stmt = delete(self.model)
        stmt = self._apply_filters(stmt, filters)
        result = await self.session.execute(stmt)
        self._log.debug("Deleted many", count=result.rowcount)
        return result.rowcount

    # === HELPERS ===

    def _apply_filters(self, stmt: Select, filters: dict[str, Any]) -> Select:
        """Применить фильтры к запросу"""
        for key, value in filters.items():
            if value is None:
                continue

            # Поддержка операторов: field__gt, field__in, field__like
            if "__" in key:
                field_name, operator = key.rsplit("__", 1)
                column = getattr(self.model, field_name, None)
                if column is None:
                    continue

                if operator == "gt":
                    stmt = stmt.where(column > value)
                elif operator == "gte":
                    stmt = stmt.where(column >= value)
                elif operator == "lt":
                    stmt = stmt.where(column < value)
                elif operator == "lte":
                    stmt = stmt.where(column <= value)
                elif operator == "in":
                    stmt = stmt.where(column.in_(value))
                elif operator == "not_in":
                    stmt = stmt.where(column.not_in(value))
                elif operator == "like":
                    stmt = stmt.where(column.like(f"%{value}%"))
                elif operator == "ilike":
                    stmt = stmt.where(column.ilike(f"%{value}%"))
                elif operator == "is_null":
                    if value:
                        stmt = stmt.where(column.is_(None))
                    else:
                        stmt = stmt.where(column.isnot(None))
                elif operator == "ne":
                    stmt = stmt.where(column != value)
            else:
                column = getattr(self.model, key, None)
                if column is not None:
                    stmt = stmt.where(column == value)

        return stmt

    def _apply_ordering(
        self,
        stmt: Select,
        order_by: str | None,
        desc: bool = True
    ) -> Select:
        """Применить сортировку"""
        if order_by and hasattr(self.model, order_by):
            column = getattr(self.model, order_by)
            stmt = stmt.order_by(column.desc() if desc else column.asc())
        return stmt

    def _with_relations(self, stmt: Select, *relations: str) -> Select:
        """Загрузить связанные объекты"""
        for relation in relations:
            if hasattr(self.model, relation):
                stmt = stmt.options(selectinload(getattr(self.model, relation)))
        return stmt
