# Codex 协作最高目标

你的最终任务不是开发一个 Python 项目，而是持续演进 HPM-DT（High-Power Microwave Digital Twin），构建一个面向高功率微波相控阵、效应分析与数字孪生研究的全中文科研级 CAE 平台。所有版本开发都必须服务于这个长期目标，而不是孤立地增加功能。

## 平台定位

HPM-DT 不是算法仓库，不是单个论文项目，也不是几个 Python 脚本。它的长期定位是：

> 高功率微波数字孪生 CAE 平台。

长期对标对象是 MATLAB Phased Array Toolbox、COMSOL App、CST/HFSS 后处理、数字孪生平台和科研论文流水线的组合能力。

## 八层长期架构

1. 物理建模层 Physics Layer：阵列、传播、多径、孔缝、腔体、近场、远场、材料。
2. 感知层 Perception Layer：DOA、MUSIC、ESPRIT、CNN、Transformer、目标识别。
3. 防护层 Protection Layer：MVDR、LCMV、宽零陷、鲁棒波束形成、动态防护。
4. 控场层 Field Control Layer：区域赋形、多目标控场、RIS、协同阵列、鲁棒优化。
5. 效应层 Effect Layer：剂量、风险、概率、敏感度、数字孪生。
6. 可信度层 Verification & Validation Layer：解析验证、文献复现、不确定度、适用性、可信度评分。
7. CAE 平台层 Workbench Layer：项目、建模、求解、结果、报告、数据库。
8. 论文生产层 Publication Layer：实验、统计、图表、LaTeX、IEEE 模板、论文自动生成。

## 阶段路线

- V2.0A：可信度验证体系 V&V。
- V2.0B：真正三维 CAE 编辑器，优先考虑 Three.js / VTK。
- V2.0C：插件系统与 Plugin Marketplace。
- V2.0D：论文自动生产线 Paper Factory。
- V3.0：接入 CST、HFSS、测量数据、CSV、Touchstone、HDF5。
- V4.0：形成可支撑软件著作权、SCI 论文体系、博士课题、项目申报和实验室公共平台的 HPM 数字孪生平台。

## 开发判断标准

每次修改都要先判断：

1. 是否让 HPM-DT 更像科研级 CAE 平台，而不是更像脚本集合？
2. 是否增强八层架构中的某一层，并保持层间接口清晰？
3. 是否能被验证、复现、审计，并最终进入报告、论文或项目申报材料？
4. 是否保持全中文界面、报告、图题、表格和说明文档？
5. 是否遵守归一化、公开、可复现、安全边界，不输出真实毁伤概率、真实作用距离、真实器件阈值或真实源功率？

## 当前里程碑

当前交付包处于 V2.0A 阶段。V2.0A 是可信度层的阶段成果，不是平台最高目标。后续开发不得把“开发某个 V2.x 功能”重新写成 North Star。

## 关键文档

- `docs/HPM_DT_NORTH_STAR.md`：HPM-DT 最高层目标。
- `docs/HPM_DT_ROADMAP.md`：V2.x、V3.0、V4.0 长期路线图。
- `docs/SAFETY_SCOPE.md`：研究安全边界。
- `docs/可信度验证体系_V20A.md`：V2.0A 可信度验证体系。
