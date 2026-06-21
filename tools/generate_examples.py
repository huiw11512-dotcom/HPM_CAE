from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hpmdt.application.factories import city_dynamic_project, static_multi_receiver_project  # noqa: E402
from hpmdt.infrastructure.project_store import ProjectStore  # noqa: E402

store = ProjectStore()
store.save(ROOT / "examples" / "城市多对象动态覆盖.hpmdt", city_dynamic_project())
store.save(ROOT / "examples" / "多接收器静态场调查.hpmdt", static_multi_receiver_project())
print("示例工程已生成")
