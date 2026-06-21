"""面向任务参与对象选择的轻量查询语法。"""
from __future__ import annotations

from hpmdt.domain.models import Entity


def matches(entity: Entity, expression: str) -> bool:
    """判断实体是否匹配查询。

    支持：
    - role:trackable
    - component:array
    - tag:group-a
    - id:<uuid>
    - enabled:true / enabled:false
    - 多条件使用空格或 ``and`` 连接，按逻辑与处理。
    """
    normalized = expression.replace(" and ", " ").strip()
    if not normalized:
        return True
    tokens = [token for token in normalized.split() if token]
    for token in tokens:
        if ":" not in token:
            return False
        key, value = token.split(":", 1)
        key = key.lower().strip()
        value = value.strip()
        if key == "role" and not entity.has_role(value):
            return False
        if key == "component" and not entity.has_component(value):
            return False
        if key == "tag" and value not in entity.tags:
            return False
        if key == "id" and entity.id != value:
            return False
        if key == "enabled" and entity.enabled != (value.lower() == "true"):
            return False
    return True


def select(entities: list[Entity], expression: str) -> list[Entity]:
    return [entity for entity in entities if matches(entity, expression)]
