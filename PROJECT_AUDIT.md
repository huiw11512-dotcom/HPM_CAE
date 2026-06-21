# HPM-DT 项目审计

更新时间：2026-06-21

## 工程规则审计

| 规则 | 当前落实 |
|---|---|
| 新增功能必须增加测试 | 新增平台成熟度和主控台模块配套 `tests/test_platform_readiness.py`；材料代理审计配套 `tests/test_workbench3d_v20b.py`；正式证据包审计配套 `tests/test_data_import_v30.py` |
| 禁止复制已有功能 | 主控台和成熟度报告复用 V&V、Workbench、DataImport、Plugin、PaperFactory 服务结果；证据包审计复用 V3.0 数据导入、证据链与外部 V&V 审计 |
| 禁止孤立算法 | 主控台、成熟度评估、材料代理审计、证据链/证据包审计、数据导入插件、论文模板插件和 Paper Factory 均接入配置、API/UI、报告产物或插件 manifest |
| 禁止硬编码 | 成熟度评分进入 `configs/platform_readiness.yaml`；外部数据授权/源链/相位参考门槛进入 `configs/external_data_evidence.yaml`；论文工厂引用、复现注册、多模板、插件模板源和 LaTeX 审计进入 `configs/paper_factory_v20d.yaml` |
| 论文适应平台 | Paper Factory 读取平台 V&V 结果并生成引用库、复现注册表、统计审计、多模板矩阵、插件模板合并和 LaTeX 审计，不为论文临时改核心求解 |

## 安全边界

平台长期保持归一化研究平台定位；报告必须说明不替代 CST/HFSS/COMSOL，不输出真实毁伤概率、真实作用距离或真实器件失效预测。

## 当前风险

- V3.0 已具备正式证据包审计入口，但仍缺可公开复查的真实源链、相位参考和授权测量数据包。
- V2.0B 三维编辑器仍缺完整尺寸/旋转 Gizmo、多用户调度器和正式工程数据库。
- V2.0D Paper Factory 仍缺外部 DOI 绑定、真实授权数据论文证据链、外部目标期刊模板签名和本机 PDF 编译归档。
