# 平台成熟度与发文准备度报告

## 目标

平台成熟度报告用于回答两个工程问题：

- 当前 HPM-DT 主链路接通到什么程度；
- 距离“可本地使用、可支撑论文初稿、可进入真实数据闭环”还差什么。

它不是物理效应预测软件，不输出真实毁伤概率、真实作用距离或真实器件阈值。

## 配置

评分权重、门槛和安全边界统一放在：

```text
configs/platform_readiness.yaml
```

新增或调整维度时必须先改配置，再改实现和测试。

## 入口

```text
GET /api/platform/readiness
```

UI 入口：

```text
平台成熟度
```

## 输入证据

报告复用现有服务结果：

- V2.0A V&V 总览、可信度评分、不确定度和敏感性；
- V2.0B 三维 Workbench 场景、材料代理审计、求解结果、资产台账、SQLite 审计、谱系、复现审计、绝对量纲标定、导入标定桥接；
- V3.0 数据导入目录、标定准备度、CalibrationSamples 桥接、模型误差对比、外部数据 V&V 审计；
- V3.0 外部数据证据链、证据包审计、证据包 V&V 候选评分与相位参考审计；
- V2.0C 插件市场目录和验收；
- V2.0D Paper Factory 论文草稿包、多模板矩阵、插件模板源、引用库、文献复现注册表、统计审计、模板审计和 LaTeX 编译审计状态；
- 全量测试报告和本地工程产物。

## 输出产物

```text
outputs_v20a_vv/platform_readiness/platform_readiness_report.json
outputs_v20a_vv/platform_readiness/platform_readiness_dimensions.csv
```

## 解释规则

- 使用准备度：面向本地演示、预实验复现和平台操作的成熟度。
- 发文准备度：面向论文草稿、图表、统计、复现材料和数据证据链的成熟度。
- 平台成熟度：面向 HPM-DT 八层长期架构的综合成熟度。

当前 V3.0 外部数据如果缺真实源链、相位参考、校准证书和授权测量数据闭环，只能作为预评分附注，不能改写正式可信度评分。相关证据从 `configs/external_data_evidence.yaml` 读取，并输出 `evidence_chain_report.json/csv`。用户也可以通过 `/api/data-import/evidence-package/template` 生成含每阵元功率和实测标定点 CSV 的证据包模板，再通过 `/api/data-import/evidence-package` 提交本机 ZIP/目录证据包，生成 `evidence_package_audit.json/csv`；通过 `/api/data-import/evidence-package/vv-candidate` 可进一步生成 `evidence_package_vv_candidate.json`，把通过审计的证据包接入源链、相位参考、残差和 2σ 覆盖率门槛。平台成熟度报告会优先读取最新的 `evidence_package_vv_candidate.json`，并在“真实数据接入”维度和主链路中显示“证据包候选评分”状态；如果没有用户提交过证据包候选报告，才使用默认模板生成阻断态候选报告。该入口只给出候选评分状态，不会绕过 V&V 残差和人工复核门槛，也不会自动改写正式可信度评分。
