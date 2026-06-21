# V2.0D Paper Factory 论文自动生产线

V2.0D 的目标是把 HPM-DT 的 Publication Layer 工程化：实验、统计、图表、LaTeX、IEEE 模板和论文自动生成都应成为平台能力，而不是手工整理结果。

当前实现是预览版，重点完成从 V&V 机器结果到可复现论文草稿包的自动生成。

## 当前能力

- 入口模块：`src/hpm_platform/publication/paper_factory.py`
- 配置文件：`configs/paper_factory_v20d.yaml`
- 模板插件：`plugins/builtin/paper_template_pack.json`
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
| `templates/*.tex` | IEEE 会议、中文期刊、学位论文章节和插件声明模板矩阵 |
| `HPM_DT_V20D_引用库.bib` | 由配置生成的 BibTeX 引用库，默认包含平台、V&V 报告和成熟度审计证据 |
| `HPM_DT_V20D_文献复现注册表.csv` | 平台证据、V&V 用例和待绑定外部 DOI 的复现登记表 |
| `HPM_DT_V20D_统计审计.json/csv` | 图表、表格、V&V 用例、不确定度和敏感性是否满足发文预览门槛 |
| `HPM_DT_V20D_模板审计.json/csv` | 检查模板数量、正文结构、必需章节和引用库入口 |
| `HPM_DT_V20D_LaTeX编译审计.json/log` | LaTeX 结构审计；若本机存在编译器则记录实际编译结果 |
| `HPM_DT_V20D_图表清单.csv` | 自动收集 V&V 图表、3D 工作台截图和插件市场截图 |
| `HPM_DT_V20D_补充材料索引.md` | 补充材料入口，索引图表、表格、机器结果和测试报告 |
| `paper_factory_manifest.json` | 论文包机器清单和验收状态 |
| `HPM_DT_V20D_paper_factory_bundle.zip` | 可复现论文材料包 |

## 安全边界

Paper Factory 只把已经验证的归一化模型结果组织成科研草稿，不生成或暗示真实源功率、器件阈值、现实作用距离或真实毁伤概率。论文定稿前必须补充文献复现、真实数据导入、外部仿真对比和更大样本统计检验。

## 下一步

- 增加实验设计器和批量复算索引；
- 把外部文献 DOI、正式复现实验编号和真实授权数据证据链绑定进复现注册表；
- 在真实授权数据闭环后生成统计显著性、置信区间和效应量段落；
- 在本机安装 LaTeX 工具链后归档可编译 PDF；
- 把内置论文模板插件扩展为可签名的外部目标期刊模板包。
