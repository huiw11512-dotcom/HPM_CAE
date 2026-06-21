# HPM-DT 架构说明

HPM-DT 按八层长期架构演进。新增能力必须接入 UI、配置系统、数据库、报告系统中的至少两个，避免孤立算法。

| 层级 | 职责 | 当前代表模块 |
|---|---|---|
| Physics Layer | 阵列、传播、多径、近场、远场、材料、孔缝、腔体 | `src/hpm_platform/physics/` |
| Perception Layer | MUSIC、ESPRIT、FBSS、PAWR、CNN、Transformer | `src/hpm_platform/perception/` |
| Protection Layer | MVDR、LCMV、宽零陷、鲁棒防护 | `src/hpm_platform/protection/` |
| Field Control Layer | 区域赋形、多目标控制、RIS、协同阵列 | `src/hpm_platform/field_control/` |
| Effect Layer | 归一化剂量、风险地图、概率响应、数字孪生 | `src/hpm_platform/evaluation/` |
| Validation Layer | Verification、Validation、Benchmark、Uncertainty、Sensitivity | `src/hpm_platform/validation/` |
| CAE Layer | UI、项目管理、实验数据库、插件系统 | `src/hpm_platform/ui/`、`src/hpm_platform/plugins/` |
| Publication Layer | 自动统计、自动绘图、LaTeX、IEEE 模板、论文生成 | `src/hpm_platform/publication/` |

## 主控链路

V2.x 当前主链路为：

主控台 -> 新建/加载工程 -> 三维 Workbench 资产台账 -> 运行归一化求解 -> V&V 结果 -> 数据导入标定桥接 -> 插件目录 -> Paper Factory -> 平台成熟度与发文准备度报告。

`/api/platform/mission-control` 面向 UI 汇总可见主链路、快速入口和发文/使用差距；`configs/platform_readiness.yaml` 管理成熟度权重、门槛和安全边界，`src/hpm_platform/readiness.py` 只执行配置化评估。
