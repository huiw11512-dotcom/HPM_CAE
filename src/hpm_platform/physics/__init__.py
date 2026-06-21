"""物理模型与插件式归一化场求解后端。"""

from hpm_platform.physics.field_backends import (
    available_field_backends,
    backend_choices,
    get_field_backend,
    register_field_backend,
)

__all__ = [
    "available_field_backends",
    "backend_choices",
    "get_field_backend",
    "register_field_backend",
]
