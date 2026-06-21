# HPM-DT 高功率微波数字孪生 CAE 平台（全 Python、全中文）

HPM-DT（High-Power Microwave Digital Twin）的长期目标，是构建一个面向高功率微波相控阵、效应分析与数字孪生研究的全中文开源科研级 CAE 平台。它不是一个算法仓库、单个论文项目或几个 Python 脚本，而是持续演进的高功率微波数字孪生 CAE 平台。

V2.0A 只是当前阶段里程碑：它完成可信度验证体系；当前工作已经开始推进 V2.0B 三维 CAE 编辑器原型和 V2.0C 插件市场预览。V1.4 的 FastAPI + Bootstrap 5 Dashboard + Plotly 离线工作台、插件式传播后端、模型适用性诊断和参数标定能力全部保留。

> **North Star**：所有版本开发都必须服务于 HPM-DT 长期平台目标，而不是孤立地增加功能。长期架构包括物理建模、感知、防护、控场、效应、可信度、CAE 工作台和论文生产八层。

> **研究边界**：平台核心求解仍处理波长尺度几何、归一化标量复场、相对阵列响应与无量纲代理评价。V2.0B 支持把用户输入的阵元功率作为实测标定元数据，并输出校准系数、残差和不确定度；它不是 CST/HFSS/COMSOL 级全波求解器，也不输出现实器件阈值、毁伤概率或作用距离。

## 长期架构

HPM-DT 的目标形态对标 MATLAB Phased Array Toolbox、COMSOL App、CST/HFSS 后处理、数字孪生平台和科研论文流水线的组合能力。

| 层级 | 名称 | 主要职责 |
|---|---|---|
| 1 | 物理建模层 Physics Layer | 阵列、传播、多径、孔缝、腔体、近场、远场、材料 |
| 2 | 感知层 Perception Layer | DOA、MUSIC、ESPRIT、CNN、Transformer、目标识别 |
| 3 | 防护层 Protection Layer | MVDR、LCMV、宽零陷、鲁棒波束形成、动态防护 |
| 4 | 控场层 Field Control Layer | 区域赋形、多目标控场、RIS、协同阵列、鲁棒优化 |
| 5 | 效应层 Effect Layer | 剂量、风险、概率、敏感度、数字孪生 |
| 6 | 可信度层 Verification & Validation | 解析验证、文献复现、不确定度、适用性、可信度评分 |
| 7 | CAE 平台层 Workbench Layer | 项目、建模、求解、结果、报告、数据库 |
| 8 | 论文生产层 Publication Layer | 实验、统计、图表、LaTeX、IEEE 模板、论文自动生成 |

长期目标详见 `docs/HPM_DT_NORTH_STAR.md`，阶段路线图详见 `docs/HPM_DT_ROADMAP.md`。

## 启动

```bash
python -m pip install -r requirements.txt
python run_vv_v20a.py
python run_ui_v20a.py
```

浏览器访问：

```text
http://127.0.0.1:7860
```

如需启动旧版工作台，仍可运行 `python run_ui_v14.py`。

## 当前里程碑：V2.0A 可信度验证体系

- 新增 6 类自动 V&V 用例：阵列因子、扫描波束、Green 函数、MUSIC/ESPRIT/PAWR、MVDR/LCMV、传播后端退化；
- 新增 Monte Carlo 不确定度、OAT 敏感性排序和 0-100 可信度评分；
- 新增 FastAPI + Bootstrap 5 “可信度验证中心”，包含总览卡片、交互图、同步运行按钮和下载端点；
- 生成中文 HTML 报告、JSON/CSV/LaTeX 表格、论文图包、中文技术说明、论文提纲和已执行 Notebook；
- 生成三张中文 SVG/PNG 示意图：可信度验证体系总架构、解析解对比机理、传播后端退化验证；
- 当前快速验收：6/6 V&V 用例通过，可信度评分 91.58/A，全量 pytest 134 项通过。

## V2.0B 三维 CAE 编辑器原型

- 新增本地 Three.js 0.166.1 三维视口，不依赖公共 CDN；
- 新增 `/api/workbench3d/scene`、`/api/workbench3d/objects/{object_id}`、`/api/workbench3d/materials/{material_id}`、`/api/workbench3d/absolute-calibration`、`/api/workbench3d/solve`、`/api/workbench3d/solve-jobs`、任务审计/暂停/恢复/取消/重试、`/api/workbench3d/results`、`/api/workbench3d/assets`、`/api/workbench3d/assets/audit`、`/api/workbench3d/assets/database`、`/api/workbench3d/assets/database/records`、`/api/workbench3d/assets/lineage`、`/api/workbench3d/assets/reproducibility`、`/api/workbench3d/assets/imported-calibration`、`/api/workbench3d/assets/naming`、`/api/workbench3d/reset`、撤销/重做、工程快照和快照差异 API；
- 场景 JSON 覆盖阵列、观察面、目标区、保护区、反射面、孔缝、腔体、远场源和材料库；
- 新增工程对象树、属性面板、材料设置、绝对量纲标定卡片、三维拖拽移动、受控几何变换控件、求解联动、求解任务队列生命周期控制、后台 worker 检查点、暂停/恢复、结果图层回写、对象级指标列表/三维徽标、结果档案复查/导出、工程快照落盘/恢复/差异对比、统一工程资产台账筛选、数据库浏览、资产谱系追溯、可复现实验审计、审计和命名规范检查、视图重置和场景快照导出；
- 属性、材料和几何变换修改回到后端 `CAEProject` 做几何/材料边界校验；三维工作台求解联动复用现有快速 CAE 求解器并返回指标摘要、对象级约束、适用性提示、V&V 适用性诊断层、观察面归一化场强 heatmap、色标、中心剖面采样、x/y 剖面交互曲线和目标/保护区对象指标；绝对量纲标定支持每阵元输入功率元数据和实测点 CSV，输出 `absolute_calibration.json`、`absolute_calibration_points.csv` 与 `absolute_element_powers.csv`，只给出校准系数、残差、2σ覆盖率和实测距离覆盖区间；每次求解生成 `JOB-xxxx` 任务记录和 `SOL-xxxx` 结果档案并保存完整 JSON，支持任务审计、后台 worker 检查点、暂停/恢复、重试派生和取消请求操作日志；后台任务可通过 `background`/`start_paused` 提交，并在任务 JSON 中保留提交时 `CAEProject` 快照，恢复时从该快照继续；同时维护求解任务、结果、工程快照和统一工程资产台账的 `index.json`/`index.csv`/`assets.sqlite`/`audit.json`/`audit.csv` 轻量索引；`assets.sqlite` 已增加 `workbench3d_solve_jobs`、`workbench3d_solve_job_events`、`workbench3d_results`、`workbench3d_snapshots` 和 `workbench3d_database_manifest` 表，支持记录提交、暂停、恢复、启动、完成、取消等 worker 事件，并可浏览任务/结果/快照库表记录；资产谱系已输出 `lineage.json`/`lineage.csv`，把快照、任务、结果、重试和事件派生关系展开为可审计节点-边；可复现实验审计输出 `reproducibility_audit.json`/`reproducibility_audit.csv`；资产命名审计已固化 `JOB-xxxx`、`SOL-xxxx`、`SNP-xxxx` 编号和 `scene_hash`/`field_hash` 文件名绑定，并输出 `naming_audit.json`/`naming_audit.csv`；资产台账支持按资产类型、标签、哈希和路径筛选，服务重启后可恢复列表并对比两份工程快照的对象/材料字段差异。

## V2.0C 插件市场预览

- 新增 `src/hpm_platform/plugins/registry.py`，支持本地 JSON manifest、语义版本校验、参数 Schema、依赖声明和安全边界声明；
- 新增 `plugins/builtin/` 三类内置插件：传播后端、感知基准、V&V 报告模板；
- 新增 `/api/plugins/catalog`、`/api/plugins/acceptance`、`/api/plugins/{plugin_id}/enable`、`/api/plugins/{plugin_id}/run`；
- 插件运行限制在平台白名单 `builtin_hook` 内，不从 manifest 导入任意 Python 模块；
- V2.0A 工作台新增“插件市场”页面，显示目录、启停状态、参数 Schema 验收和运行审计结果。

## V2.0D Paper Factory 预览

- 新增 `src/hpm_platform/publication/paper_factory.py`，从最新 V&V 机器结果自动生成论文材料；
- 自动生成 Markdown 论文草稿、IEEE LaTeX 骨架、图表清单 CSV、补充材料索引和可复现论文包 ZIP；
- 新增 `/api/paper-factory/status`、`/api/paper-factory/generate` 和 `/download/paper-factory.zip`；
- V2.0A 工作台“论文报告导出”页新增论文草稿包生成和下载控件；
- 论文包保留模型安全边界，不把归一化代理结果写成真实毁伤概率、真实作用距离或器件阈值。

## V3.0 数据导入预览

- 新增 `src/hpm_platform/data_import/importers.py`，支持 CST/HFSS 导出包、测量数据批次、CSV、Touchstone、NPZ、HDF5 的格式识别和元数据审计；
- 自动生成内置样例：近场 CSV、S2P Touchstone、复场 NPZ、HDF5 样例/签名桩、CST 导出包、HFSS/AEDT 导出包和 Measurement Campaign 测量批次；
- 新增 `/api/data-import/catalog`、`/api/data-import/acceptance`、`/api/data-import/calibration-readiness`、`/api/data-import/calibration-bridge`、`/api/data-import/model-comparison`、`/api/data-import/vv-audit`、`/api/data-import/samples/{sample_id}`、`/api/data-import/inspect`；
- V2.0A 工作台新增“数据导入”页面，可查看样例、验收清单、单位/坐标列、标定准备度和解析结果；
- 新增导入数据标定准备度报告，可预览 `mm -> lambda` 坐标规范化、归一化复场样本数、不确定度字段和校准状态；
- 新增导入数据标定桥接报告，把 Measurement Campaign 归一化复场样本构造成 `CalibrationSamples`，并用当前工程生成的代理激励运行标定 smoke preview；
- 三维 Workbench 已自动读取导入数据桥接、模型误差对比和外部数据 V&V 审计，生成 `IMP-CAL-001` 资产与 `imported_calibration_bridge.json/csv`，在绝对量纲标定卡片和资产台账中显示样本数、相对 RMSE、2σ 覆盖率和正式评分门槛状态；
- 新增导入数据模型误差对比报告，输出代理模型复场残差、RMSE 改善、p95 残差和基于测量 1-sigma 字段的 1σ/2σ 覆盖率；
- 新增外部数据 V&V 可信度审计，把模型残差和测量不确定度传播为预评分、风险信号和正式纳入门槛；当前源链/相位参考未接入时不改写 V2.0A 核心评分；
- 导入层只做数据血缘、单位、坐标系、校准状态、不确定度、复数值和安全边界审计，不把外部数据直接解释为真实毁伤或作用距离结论。

后续规划包括：补齐 V2.0B 真正三维拖拽式尺寸/旋转 Gizmo、工厂级资产/快照命名策略、正式多用户调度器和工程/结果数据库管理，扩展 V2.0C 插件级 V&V、外部插件签名/沙箱和保护/控场插件，补齐 V2.0D 多模板、引用库和 LaTeX 编译验收，并把 V3.0 数据导入继续推进到真实源链/相位参考接入、正式可信度评分纳入和授权外部数据闭环标定报告。V4.0 面向实验室公共 HPM 数字孪生平台。

## V1.4 保留能力

- 全中文 Bootstrap 5 官方 Dashboard 模板工作台；
- 本地 FastAPI + Jinja2 服务，无公共 CDN 依赖；
- 自由空间、镜像射线、孔缝—腔体降阶、混合场景四类传播后端；
- 多目标约束控场、功放代理与 DPD；
- 四后端同工程对比；
- 数值模型适用性评分与逐项边界提示；
- 直达、反射、腔体三个归一化传播尺度的鲁棒联合标定；
- 标定前后 RMSE、R²、收敛和空间残差复核；
- 三张高分辨率中文 PNG/SVG 机理图，已嵌入 UI 与报告；
- 中文交互验收报告、CSV/JSON 数据和 SHA-256 清单；
- V0.1—V1.3 的感知、防护、动态控场、效应代理和实验管理代码全部保留。

## 默认快速验收结果

| 指标 | 结果 |
|---|---:|
| 目标区总体 RMSE | 7.35% |
| 最低目标覆盖率 | 80.16% |
| 区外峰值 | −2.39 dB |
| 混合后端适用性得分 | 97.60 / 100 |
| 参数标定前相对 RMSE | 41.99% |
| 参数标定后相对 RMSE | 0.24% |
| 联合归一化控制判据 | 通过 |
| 自动测试 | 134 项全部通过 |

标定算例含 0.25% 归一化复场噪声；结果用于软件验收和方法展示，不等同于全波或实物验证。

## 主要入口

```text
docs/HPM_DT_NORTH_STAR.md                         HPM-DT 最高层目标
docs/HPM_DT_ROADMAP.md                            V2.x/V3.0/V4.0 长期路线图
AGENTS.md                                         Codex/开发者协作最高目标
run_vv_v20a.py                                    V2.0A 命令行可信度验证
run_ui_v20a.py                                    V2.0A 可信度验证中心
run_ui_v14.py                                      V1.4 中文工作台
configs/vv/                                       V2.0A V&V 阈值与用例配置
docs/CAE_WORKBENCH_V20B.md                        V2.0B 三维 CAE 编辑器原型说明
src/hpm_platform/ui/workbench3d.py                V2.0B 三维场景服务
src/hpm_platform/validation/vv_runner.py          V2.0A 验证体系运行器
src/hpm_platform/ui/app_v20a.py                   V2.0A FastAPI 路由
outputs_v20a_vv/v20A_可信度验证报告.html          V2.0A 中文验证报告
configs/cae_project_v14.yaml                       默认验证与标定工程
src/hpm_platform/ui/app_v14.py                     FastAPI 路由
src/hpm_platform/ui/v14_service.py                 工作台业务服务
src/hpm_platform/ui/templates_v14/index.html       Bootstrap 中文模板
src/hpm_platform/ui/static_v14/                    本地前端资源与机理图
src/hpm_platform/validation/model_validity.py      模型适用性诊断
src/hpm_platform/validation/backend_calibration.py 传播尺度标定
scripts/build_v14_acceptance.py                    一键生成验收产物
outputs_v14_ui/v14_验收报告.html                  自包含交互报告
notebooks/10_cae_v14_模型适用性与参数标定快速复现_已执行.ipynb
papers/paper4_model_validation_v14_outline.md
```

## 图片说明

当前会话没有开放 image2，因此本版三张正式机理图由本地 Python 生成，同时提供可编辑 SVG；项目没有把它们冒充为 image2 产物。资源已经真实放入 UI、验收报告和压缩包，生成脚本可复现。

## 开源组件

界面使用 Bootstrap 5.1.1、Bootstrap Icons 与 Plotly.js，前端资源均已本地化。许可证见 `THIRD_PARTY_NOTICES.md` 与 `licenses/`。

## 文档

- `docs/HPM_DT_NORTH_STAR.md`：HPM-DT 长期最高层目标；
- `docs/HPM_DT_ROADMAP.md`：V2.x、V3.0、V4.0 路线图；
- `AGENTS.md`：Codex/开发者协作最高目标；
- `docs/CAE_WORKBENCH_V14.md`：V1.4 完整技术说明；
- `docs/可信度验证体系_V20A.md`：V2.0A 可信度验证体系；
- `docs/CAE_WORKBENCH_V20B.md`：V2.0B 三维 CAE 编辑器原型；
- `docs/SAFETY_SCOPE.md`：研究边界；
- `outputs_v20a_vv/v20A_可信度验证报告.html`：V2.0A 中文验证报告；
- `outputs_v14_ui/v14_验收报告.html`：图文验收结果。
