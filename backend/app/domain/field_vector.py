"""Vector ORM field refactored from et-addons/ai/orm/field_vector.py."""
import json
import math
from sqlalchemy.types import TypeDecorator, TEXT


def pg_vector(size: int) -> str:
    if not isinstance(size, int):
        raise TypeError(f"vector size should be an int, got {size!r}")
    if size > 0:
        return "vector(%d)" % size
    return "vector"


class Vector(TypeDecorator):
    """SQLAlchemy equivalent of Odoo's Vector(fields.Field) in et-addons/ai/orm/field_vector.py.
    Stores JSON-serialized float vectors and supports pgvector column type on PostgreSQL.
    """

    impl = TEXT
    cache_ok = True

    def __init__(self, size: int = 1536, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert size is None or isinstance(size, int), f"Vector field with non-integer size {size!r}"
        self.size = size

    def process_bind_param(self, value, dialect):
        if value is None or value is False:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(list(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, list):
            return value
        return json.loads(value)


def cosine_similarity(vec_a: list[float] | None, vec_b: list[float] | None) -> float:
    """Compute 1 - (vec_a <=> vec_b) cosine similarity."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)

