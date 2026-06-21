# HPM-DT 项目审计

更新时间：2026-06-21

## 工程规则审计

| 规则 | 当前落实 |
|---|---|
| 新增功能必须增加测试 | 新增平台成熟度和主控台模块配套 `tests/test_platform_readiness.py` |
| 禁止复制已有功能 | 主控台和成熟度报告复用 V&V、Workbench、DataImport、Plugin、PaperFactory 服务结果；证据链审计复用 V3.0 数据导入与外部 V&V 审计 |
| 禁止孤立算法 | 主控台、成熟度评估、证据链审计、数据导入插件和 Paper Factory 均接入配置、API/UI、报告产物或插件 manifest |
| 禁止硬编码 | 成熟度评分进入 `configs/platform_readiness.yaml`；外部数据授权/源链/相位参考门槛进入 `configs/external_data_evidence.yaml`；论文工厂引用、复现注册、多模板和 LaTeX 审计进入 `configs/paper_factory_v20d.yaml` |
| 论文适应平台 | Paper Factory 读取平台 V&V 结果并生成引用库、复现注册表、统计审计、多模板矩阵和 LaTeX 审计，不为论文临时改核心求解 |

## 安全边界

平台长期保持归一化研究平台定位；报告必须说明不替代 CST/HFSS/COMSOL，不输出真实毁伤概率、真实作用距离或真实器件失效预测。

## 当前风险

- V3.0 外部数据仍缺真实源链、相位参考和授权测量数据闭环。
- V2.0B 三维编辑器仍缺完整尺寸/旋转 Gizmo、多用户调度器和正式工程数据库。
- V2.0D Paper Factory 仍缺外部 DOI 绑定、真实授权数据论文证据链、目标期刊模板插件和本机 PDF 编译归档。
