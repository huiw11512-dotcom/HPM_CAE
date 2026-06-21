# V2.0C 插件系统与 Plugin Marketplace

V2.0C 的目标是把 HPM-DT 从内置模块集合推进为可扩展平台。当前实现是第一阶段预览：插件以本地 JSON manifest 注册，平台只执行白名单内置钩子，不从 manifest 导入任意 Python 模块。

## 当前能力

- 本地插件目录：`plugins/builtin/`
- 插件注册表：`src/hpm_platform/plugins/registry.py`
- 工作台页面：V2.0A UI 侧栏“插件市场”
- API：

```text
GET  /api/plugins/catalog
GET  /api/plugins/acceptance
GET  /api/plugins/{plugin_id}
POST /api/plugins/{plugin_id}/enable
POST /api/plugins/{plugin_id}/run
```

## 内置插件

| 插件 ID | 类别 | 层级 | 入口点 |
|---|---|---|---|
| `hpm.propagation.hybrid_scene` | `propagation_backend` | Physics Layer | `field_backend_summary` |
| `hpm.perception.music_esprit_benchmark` | `perception_algorithm` | Perception Layer | `perception_benchmark_summary` |
| `hpm.data_import.evidence_chain` | `data_import_adapter` | CAE Layer | `data_import_summary` |
| `hpm.publication.vv_report_pack` | `report_template` | Publication Layer | `report_template_summary` |
| `hpm.publication.paper_template_pack` | `report_template` | Publication Layer | `report_template_summary` |

## Manifest 字段

```json
{
  "id": "hpm.example.plugin",
  "name": "示例插件",
  "version": "2.0.0",
  "category": "propagation_backend",
  "layer": "Physics Layer",
  "summary": "插件摘要",
  "provider": "HPM-DT 内置",
  "entry_point": {"kind": "builtin_hook", "target": "field_backend_summary"},
  "parameters_schema": {"type": "object", "properties": {}},
  "dependencies": [],
  "enabled_by_default": true,
  "safety": {"execution": "builtin_hook_only"},
  "acceptance_tests": [],
  "sample_project": "configs/cae_project_v14.yaml",
  "tags": ["V2.0C"],
  "settings": {}
}
```

## 安全边界

- 仅加载本地 JSON manifest；
- 仅执行平台内置白名单 `builtin_hook`；
- 不从插件 manifest 导入任意 Python 模块；
- 不输出绝对源功率、器件阈值、现实作用距离或毁伤概率；
- 外部插件包、签名校验、沙箱和插件级 V&V 属于后续门槛。
- `report_template` 插件可以在 `settings.paper_templates` 中声明论文模板，Paper Factory 会按 `configs/paper_factory_v20d.yaml` 的 `plugin_templates` 白名单合并这些模板。

## 下一步

- 增加保护算法和控场算法插件类型；
- 把 V3.0 数据导入插件从证据链摘要扩展到可配置导入适配器验收；
- 把插件运行绑定到三维工作台求解链路；
- 为每个插件建立 V&V 夹具和回归测试；
- 设计外部插件签名、隔离执行和版本兼容策略；
- 把论文模板插件从内置预览扩展到可签名的外部目标期刊模板包。
