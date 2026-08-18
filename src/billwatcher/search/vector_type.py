"""A single embedding column definition that works on PostgreSQL and on the offline suite.

PostgreSQL stores a real pgvector column so cosine distance and an HNSW index are available.
SQLite, which backs the offline tests, stores the same list as JSON so the chunking, embedding,
and fusion code paths can be exercised without a database server.
"""

from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine


class EmbeddingVector(TypeDecorator[list[float]]):
    impl = JSON
    cache_ok = True

    def __init__(self, dimension: int) -> None:
        super().__init__()
        self.dimension = dimension

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dimension))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: list[float] | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        if len(value) != self.dimension:
            raise ValueError(
                f"embedding has {len(value)} dimensions but the schema stores {self.dimension}"
            )
        return list(value) if dialect.name != "postgresql" else value

    def process_result_value(self, value: Any, dialect: Dialect) -> list[float] | None:
        if value is None:
            return None
        return [float(component) for component in value]
