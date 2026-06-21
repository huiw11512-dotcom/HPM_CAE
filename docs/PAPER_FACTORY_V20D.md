# V2.0D Paper Factory 论文自动生产线

V2.0D 的目标是把 HPM-DT 的 Publication Layer 工程化：实验、统计、图表、LaTeX、IEEE 模板和论文自动生成都应成为平台能力，而不是手工整理结果。

当前实现是预览版，重点完成从 V&V 机器结果到可复现论文草稿包的自动生成。

## 当前能力

- 入口模块：`src/hpm_platform/publication/paper_factory.py`
- 输出目录：`outputs_v20a_vv/paper_factory_v20d/`
- UI 页面：V2.0A 工作台“论文报告导出”
- API：

```text
GET  /api/paper-factory/status
POST /api/paper-factory/generate
GET  /download/paper-factory.zip
```

## 生成产物

| 产物 | 说明 |
|---|---|
| `HPM_DT_V20D_论文草稿.md` | 中文论文草稿，包含摘要、方法、结果、讨论、边界和可复现性 |
| `HPM_DT_V20D_IEEE骨架.tex` | IEEEtran 风格 LaTeX 骨架，保留中文支持说明 |
| `HPM_DT_V20D_图表清单.csv` | 自动收集 V&V 图表、3D 工作台截图和插件市场截图 |
| `HPM_DT_V20D_补充材料索引.md` | 补充材料入口，索引图表、表格、机器结果和测试报告 |
| `paper_factory_manifest.json` | 论文包机器清单和验收状态 |
| `HPM_DT_V20D_paper_factory_bundle.zip` | 可复现论文材料包 |

## 安全边界

Paper Factory 只把已经验证的归一化模型结果组织成科研草稿，不生成或暗示真实源功率、器件阈值、现实作用距离或真实毁伤概率。论文定稿前必须补充文献复现、真实数据导入、外部仿真对比和更大样本统计检验。

## 下一步

- 增加实验设计器和批量复算索引；
- 自动生成统计显著性、置信区间和效应量段落；
- 接入 BibTeX/CSL 引用库；
- 增加 IEEE/期刊/学位论文多模板；
- 执行 LaTeX 编译验收并输出编译日志；
- 与 V2.0C 插件市场打通论文模板插件协议。
