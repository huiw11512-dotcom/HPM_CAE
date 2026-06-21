# 版本记录

## 未发布 — 2026-06-21

- 新增平台成熟度与发文准备度主链路：`src/hpm_platform/readiness.py` 汇总 V&V、三维 Workbench、数据导入、插件市场、Paper Factory 和工程复现证据。
- 新增配置文件 `configs/platform_readiness.yaml`，统一管理成熟度权重、验收门槛和安全边界，避免硬编码评分口径。
- 新增 `/api/platform/readiness` 和 UI“平台成熟度”页面，直接展示使用准备度、发文准备度、主链路接通状态、八层成熟度和关键阻断项。
- 新增 `/api/platform/mission-control` 和 UI“主控台”首屏，把工程、三维编辑、求解、V&V、数据导入、插件和论文生产串成可见主链路。
- 平台成熟度与主控台已纳入证据包 V&V 候选评分，真实数据接入维度会显示候选报告是否存在、候选门槛是否满足以及是否保持“不自动改写正式评分”。
- 新增 `configs/paper_factory_v20d.yaml`，Paper Factory 现在自动输出 BibTeX 引用库、文献复现注册表、统计审计、IEEE/期刊/学位论文多模板、插件模板合并、模板审计、LaTeX 编译审计和前端论文生产审计表。
- Paper Factory 已把 `evidence_package_vv_candidate.json` 写入论文草稿、补充材料索引、复现注册表、统计审计和 manifest；候选未过门槛时只作为风险附注，不改写正式可信度评分。
- 新增 `hpm.publication.paper_template_pack` 内置论文模板包插件，V2.0C `report_template` 插件协议可向 V2.0D Paper Factory 暴露论文模板声明。
- 新增 Workbench 材料代理审计：`/api/workbench3d/materials/audit` 输出 `MAT-AUDIT-001`，并让平台主链路“设置材料”由可编辑提升为可审计、可入账。
- 新增 `configs/external_data_evidence.yaml`、`src/hpm_platform/data_import/evidence_chain.py` 与 `/api/data-import/evidence-chain`，审计外部数据授权、源链、相位参考、校准证书、原始数据哈希和不确定度模型。
- 新增 `/api/data-import/evidence-package` 与工作台“审计证据包”入口，支持本机 ZIP/目录证据包 manifest 解析、原始数据 SHA256 匹配和安全字段拦截，输出 `evidence_package_audit.json/csv`。
- 新增 `/api/data-import/evidence-package/template` 与工作台“生成模板”入口，输出含每阵元功率 CSV、实测标定点 CSV、manifest 和填写说明的证据包模板。
- 新增 `/api/data-import/evidence-package/vv-candidate` 与工作台“候选评分”入口，把通过审计的授权证据包接入源链、相位参考、残差和 2σ 覆盖率门槛，输出 `evidence_package_vv_candidate.json`，但不自动改写正式可信度评分。
- 新增 `hpm.data_import.evidence_chain` 内置数据导入插件，V2.0C 插件市场支持 `data_import_adapter` 类别和 `data_import_summary` 白名单钩子。
- 新增根目录项目管理文件 `VISION.md`、`ROADMAP.md`、`ARCHITECTURE.md`、`PROJECT_AUDIT.md`、`STATUS.md`。
- 新增 `tests/test_platform_readiness.py` 回归测试，覆盖配置、API、报告产物、前端入口和安全边界。

## V2.0A — 2026-06-21

- 将项目顶层定位提升为 HPM-DT（High-Power Microwave Digital Twin）长期 CAE 平台，明确 V2.0A 只是可信度层阶段里程碑。
- 新增 `docs/HPM_DT_NORTH_STAR.md` 与 `docs/HPM_DT_ROADMAP.md`，定义未来 1-2 年 North Star、八层架构和 V2.x/V3.0/V4.0 路线图。
- 新增根级 `AGENTS.md`，把 HPM-DT North Star 固化为 Codex/开发者默认协作约束。
- 新增 `src/hpm_platform/north_star.py` 平台元数据源，并将 North Star 接入 V2.0A UI、API 与机器可读 V&V 结果。
- 新增 North Star 回归测试，锁定 README、PROJECT_MANIFEST、AGENTS、路线图、UI 和 JSON 报告中的平台级定位。
- 更新 README 与 PROJECT_MANIFEST，使平台目标从“开发 V2.0A”改为“持续演进 HPM-DT 科研级 CAE 平台”。
- 新增可信度验证体系 V&V，覆盖解析解验证、算法基准验证、传播后端一致性、不确定度、敏感性和可信度评分。
- 新增 `src/hpm_platform/validation/analytic_cases.py`、`vv_runner.py`、`vv_report.py`、`plotting_vv.py` 等模块。
- 新增 `configs/vv/` 阈值与用例配置、`run_vv_v20a.py` 命令行入口和 `run_ui_v20a.py` 可信度验证中心。
- 新增中文 HTML 报告、JSON/CSV/LaTeX、论文图包、技术说明、论文提纲、Notebook 与 V&V 结果包输出。
- 新增三张中文 SVG/PNG 示意图：可信度验证体系总架构图、解析解对比机理图、传播后端退化验证图。
- 自动测试扩展至 103 项，快速 V&V 验收 6/6 通过，可信度评分 91.58/A。

## V1.4 — 2026-06-20

- 使用 FastAPI、Jinja2 和 Bootstrap 5 官方 Dashboard 开源模板结构重建全中文本地工作台。
- 新增自由空间、镜像射线、孔缝—腔体降阶与混合后端的统一适用性诊断。
- 新增直达、反射、腔体三个归一化传播尺度的 Soft-L1 鲁棒联合标定。
- 新增标定前后 RMSE、R²、收敛曲线和空间残差复核。
- 新增三张高分辨率中文 PNG/SVG 机理图，并嵌入 UI 与验收报告。
- 新增本地化 Bootstrap、Bootstrap Icons、Plotly.js 资源及第三方许可证说明。
- Schema 升级至 1.4，并保留 V0.9—V1.3 工程迁移。
- 新增中文验收报告、CSV/JSON 数据、SHA-256 清单与 V1.4 自动测试。

## 历史版本

### V1.3 — 2026-06-20

- 新增插件式场求解后端协议、注册表、后端选择和统一线性传播矩阵接口。
- 新增自由空间标量格林、一阶镜像射线、孔缝—腔体降阶和混合场景四类后端。
- 新增材料、反射面、孔缝和腔体工程对象、Schema 1.3 和旧工程迁移。
- 新增传播后端一键对比、场图画廊、性能表、中文 HTML 报告和 ZIP 导出。
- UI 改用开源 Gradio Ocean 模板与原生组件，V1.3 新增界面和文档全部中文化。
- 保留归一化、非全波、非毁伤化建模边界；未把 Graphviz 过渡图冒充为 image2 输出。

### V1.2 — 2026-06-20

- 新增对象级目标优先级、独立容差、保护区独立幅度上限和可配置区外峰值上限。
- 新增 Constrained-MO-PGMS：对象加权误差、目标公平性、保护区超限和区外尾部峰值联合优化。
- 新增幅相/配准多场景鲁棒对象分组求解和分项收敛历史。
- 新增对象级 CSV、二维有符号约束裕量图和对象公平性/保护上限可视化。
- 新增 Pareto 设计空间扫描、非支配前沿、推荐折中点和完整报告导出。
- V1.2 双目标默认工程联合判据通过；全仓库自动测试增至81项。

### V1.1 — 2026-06-20

- 感知与接收防护从历史适配器升级为实时可执行任务节点。
- 新增多目标、多保护区、多相干辐射源对象模型和Schema 1.1迁移。
- 新增PAWR/FBSS/ESPRIT对比、阵元可靠度和接收二维响应可视化。
- 新增SQLite检查点并行队列，支持暂停、恢复、取消和进程重启恢复。
- 新增配置驱动一键全链路执行与自包含HTML报告。
- 自动测试增至76项。

### V1.0.0 — 拖拽式 CAE、动态时间轴与实验管理

- 新增目标椭圆、旋转柄与保护区几何的真实拖拽编辑器。
- 新增带延迟观测和预测基线的逐帧动态 PGMS。
- 新增 Plotly 回放、轨迹视图、逐帧指标与动态 ZIP 报告。
- 新增扫参队列、重复试验、置信区间、SQLite 持久化与历史视图。
- 新增依赖闭包、拓扑执行计划与实时/适配器任务图。
- 新增 V0.9 YAML 迁移、V1.0 工程模式、验收报告、架构 SVG 与动态 GIF。
- 完整回归测试由 64 项扩展至 70 项。

### V0.9.0 — 本地可视化 CAE 工作台

- 新增基于 Gradio/Plotly 的本地浏览器工作台，包含项目树、参数检查器、求解视口和成果面板。
- 新增 YAML 工程模型，以及阵列、观察面、目标区、保护区、不确定性、功放和 DPD 配置校验。
- 新增 Point-Focus、Region-LS、Nominal-PGMS 和 Robust-PGMS 交互求解桥。
- 新增三维几何、场热图、目标截线、远场、阵元激励与收敛视图。
- 新增 YAML、独立 HTML、完整 ZIP 与校验和一键导出。
- 新增 V0.3、V0.4、V0.7、V0.8 历史结果浏览。
- 新增 13 项界面/工程/求解/报告测试，完整测试达到 64 项。

## v0.8.0

- 新增目标随体坐标系与世界固定坐标系双状态累积；
- 新增无量纲场强—剂量递推、松弛记忆和三档概率响应层；
- 新增对数正态阈值离散性、耦合不确定性和95%概率区间；
- 新增目标覆盖、概率熵、保护区P95、旁区风险面积、选择性和响应效率；
- 新增Always-on、Target-stop和EA-Duty归一化分配策略；
- 新增阈值、保持率、耦合离散性和单帧权重四类Monte Carlo扫参；
- 新增29项图形、可编辑SVG、自包含HTML和动态概率GIF；
- 新增CSV/NPZ/JSON/LaTeX、环境信息与SHA-256输出；
- 单元测试由45项扩展至51项。

## v0.7.0

- 新增二维移动目标区轨迹、延迟测量队列和执行滞后协议；
- 新增平面常速度Kalman跟踪及位置协方差传播；
- 新增协方差主轴Sigma中心、置信域外包络和动态旁区采样；
- 新增PCF-RLS：预测、协方差、硬件场景集、交替相位更新、DPD和反馈设定值修正；
- 新增时延、测量噪声、机动强度和相位误差四类逐帧Monte Carlo扫参；
- 新增动态可用率、逐帧轨迹误差、目标区RMSE/覆盖率和旁区p95评价；
- 新增组件消融、配对检验、28项图形、SVG机理图和动态GIF；
- 新增CSV/NPZ/JSON/LaTeX、自包含HTML和SHA-256输出；
- 单元测试由40项扩展至45项。

## v0.6.0

- 新增旋转椭圆目标区、保护间隔和旁区三分区近场调控协议；
- 新增标量Green矩阵参考归一化和Point-Focus/Region-LS基线；
- 新增Nominal-PGMS及复数Adam的RMS/峰值投影；
- 新增SR-PGMS：阵元增益、相位和控制平面配准场景联合训练；
- 新增Rapp AM/AM、有界AM/PM和逐阵元数值逆DPD；
- 新增相位误差、增益误差、配准抖动和PA饱和四类Monte Carlo扫参；
- 新增Pareto前沿、联合成功门限、配对Wilcoxon和组件消融；
- 新增22张自动图、可编辑SVG、自包含HTML、CSV/NPZ/JSON/LaTeX；
- 单元测试由27项扩展至40项。

## v0.5.0

- 新增PAWR局部MUSIC后验到二维DOA协方差的自动提取；
- 新增带时间戳的多目标常速度Kalman跟踪和滞后协方差传播；
- 新增双移动干扰、感知更新滞后和两阶段通道故障动态协议；
- 新增多扇区旋转置信椭圆、角流形SVD及轮转秩分配；
- 新增PCP-HybridNull：预测协方差、健康通道惩罚、硬/软联合零陷；
- 新增延迟、更新间隔、故障数、速度四类逐帧Monte Carlo扫参；
- 新增组件消融、配对Wilcoxon检验、尾部分位数和可用率；
- 新增20张自动图、可编辑SVG、自包含HTML和论文表格；
- 单元测试由20项扩展至27项。

## v0.4.0

- 新增训练方向与评估漂移方向分离的接收防护协议；
- 新增二维DOA置信椭圆、概率加权角流形和扇区协方差；
- 新增Point-LCMV、一阶导数LCMV、Sector-MVDR和密集扇区LCMV基线；
- 新增CR-HybridNull角域特征子空间硬零陷与软残余扇区惩罚；
- 新增WNG和条件数驱动的自适应零陷秩回退；
- 新增方向漂移、快拍数、相位失配、置信域宽度和INR五类扫参；
- 新增配对Wilcoxon检验、组件消融、运行时间和覆盖边界；
- 新增17张自动图、SVG机理图、自包含HTML和论文表格；
- 使用threadpoolctl稳定小矩阵计算，快速配置总运行时间约十余秒；
- 单元测试由14项扩展至20项。

## v0.3.0

- 新增局部接收通道增益、相位与附加噪声异常模型；
- 新增数据驱动通道健康度和自适应子阵权重；
- 新增二维BTTB投影、PSD投影与结构残差；
- 新增二维FBSS-ESPRIT强基线；
- 新增PAWR-MUSIC：宽松路径先验、连续子空间拟合与低秩协方差重构；
- 新增SNR、坏通道数、快拍数和先验偏差Monte Carlo扫参；
- 新增组件消融、配对检验、运行时间统计和论文表格；
- 新增17张自动图及可编辑SVG机理图；
- 单元测试由9项扩展至14项；
- 明确公开平台归一化与安全范围。

## v0.2.0

- 新增完全相干多径发射源与阵元幅相误差模型；
- 新增矩形阵列前向/前后向空间平滑；
- 重构二维MUSIC为可复用预计算扫描器；
- 新增信号子空间补投影快速实现及等价性测试；
- 新增球面角误差、匈牙利多峰匹配、置信区间和Wilson区间；
- 新增SNR、快拍数、阵列流形失配Monte Carlo工作流；
- 新增非相干双源消融对照；
- 新增可编辑机理图、CSV/NPZ/JSON和HTML报告；
- 保留V0.1全链路演示入口。
