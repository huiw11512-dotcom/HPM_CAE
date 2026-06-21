# 重启说明

旧平台最大问题不是功能不足，而是把手工绘制的目标区、保护区和观察面当成场景世界本身。

本次重启直接替换了领域模型：

| 旧概念 | 新概念 |
|---|---|
| TargetRegion | 任务派生的ObjectiveVolume，0.1版不再作为主对象 |
| ProtectedZone | 任务派生的ConstraintVolume，0.1版不再作为主对象 |
| ObservationPlane | 通用Plane Probe |
| 固定目标编号 | 角色/组件查询 |
| 单一优化算例 | 任意实体数量的任务 |
| 验证后台首页 | 场景编辑工作区 |
| 多版本UI入口 | 单一 `run_studio.py` |

旧算法可以未来通过适配器接入，但不得反向污染新领域模型。
