# HPM-DT 项目审计

更新时间：2026-06-21

## 工程规则审计

| 规则 | 当前落实 |
|---|---|
| 新增功能必须增加测试 | 新增平台成熟度模块配套 `tests/test_platform_readiness.py` |
| 禁止复制已有功能 | 成熟度报告复用 V&V、Workbench、DataImport、Plugin、PaperFactory 服务结果；证据链审计复用 V3.0 数据导入与外部 V&V 审计 |
| 禁止孤立算法 | 成熟度评估和证据链审计均接入配置、API、UI、报告产物和 manifest |
| 禁止硬编码 | 成熟度评分进入 `configs/platform_readiness.yaml`；外部数据授权/源链/相位参考门槛进入 `configs/external_data_evidence.yaml` |
| 论文适应平台 | Paper Factory 读取平台 V&V 结果，不为论文临时改核心求解 |

## 安全边界

平台长期保持归一化研究平台定位；报告必须说明不替代 CST/HFSS/COMSOL，不输出真实毁伤概率、真实作用距离或真实器件失效预测。

## 当前风险

- V3.0 外部数据仍缺真实源链、相位参考和授权测量数据闭环。
- V2.0B 三维编辑器仍缺完整尺寸/旋转 Gizmo、多用户调度器和正式工程数据库。
- V2.0D Paper Factory 仍缺引用库、统计显著性报告和 LaTeX 编译验收。
