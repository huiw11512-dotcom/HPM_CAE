# V2.0B 三维 CAE 编辑器原型

V2.0B 的目标是把 HPM-DT 的 Workbench Layer 从表单式参数配置推进到三维工程建模。当前版本先完成一个可运行、可测试、可继续扩展的最小闭环：后端从 `CAEProject` 生成三维场景 JSON，前端用本地 Three.js 渲染场景，对象和材料属性修改必须回到后端通过工程约束校验后才会更新，并可把当前三维工程状态送入快速 CAE 求解器生成任务记录、结果摘要、结果图层和可复查结果档案；右侧属性面板新增绝对量纲标定卡片，可记录每阵元输入功率元数据和实测标定点，并输出校准残差与不确定度；求解任务支持本地取消请求、暂停检查点、恢复执行、重试派生和操作审计；工程快照可以落盘、恢复并对比对象/材料字段差异；统一工程资产台账把 `JOB-xxxx`、`SOL-xxxx` 和 `SNP-xxxx` 汇总成 JSON、CSV、SQLite 与审计报告轻量索引，把求解任务操作日志同步写入 SQLite 事件表，并提供资产谱系追溯、可复现实验审计、资产/快照命名规范审计。

## 已接入能力

- 本地 Three.js 0.166.1 视口，不依赖公共 CDN；
- `/api/workbench3d/scene` 输出可审计场景 JSON；
- `/api/workbench3d/objects/{object_id}` 支持目标区、保护区、反射面、孔缝、腔体的受控属性更新；
- `/api/workbench3d/materials/{material_id}` 支持材料代理参数的受控更新；
- `/api/workbench3d/absolute-calibration` 支持每阵元输入功率元数据、实测标定点、校准系数、残差、2σ覆盖率和实测距离覆盖区间的读写与落盘；
- `/api/workbench3d/assets/imported-calibration` 把 V3.0 Measurement Campaign 桥接报告、模型误差对比和外部数据 V&V 审计接入三维资产台账，输出 `IMP-CAL-001`、样本数、相对 RMSE、2σ覆盖率、预评分和正式评分门槛状态；
- `/api/workbench3d/solve` 支持当前三维工程状态的快速求解联动，返回指标摘要、对象级约束、适用性提示、V&V 适用性诊断层、观察面归一化场强图层、图层统计、中心剖面采样、x/y 剖面交互曲线数据和安全边界；
- `/api/workbench3d/solve-jobs`、`/api/workbench3d/solve-jobs/audit`、`/api/workbench3d/solve-jobs/{job_id}`、`/api/workbench3d/solve-jobs/{job_id}/pause`、`/api/workbench3d/solve-jobs/{job_id}/resume`、`/api/workbench3d/solve-jobs/{job_id}/cancel` 和 `/api/workbench3d/solve-jobs/{job_id}/retry` 支持三维求解任务提交、后台worker预览、暂停检查点、恢复执行、队列列表、任务详情复查、取消请求、重试派生、操作日志、审计报告和轻量索引恢复；
- `/api/workbench3d/results` 和 `/api/workbench3d/results/{result_id}` 支持求解结果档案列表与详情复查；
- `/api/workbench3d/assets`、`/api/workbench3d/assets/audit`、`/api/workbench3d/assets/database`、`/api/workbench3d/assets/database/records`、`/api/workbench3d/assets/lineage`、`/api/workbench3d/assets/reproducibility`、`/api/workbench3d/assets/imported-calibration`、`/api/workbench3d/assets/naming` 和 `/api/workbench3d/assets/{asset_id}` 支持求解任务、求解结果、工程快照和导入标定桥接的统一资产台账、筛选、审计、SQLite 数据库审计、库表浏览、资产谱系追溯、可复现实验审计、命名规范审计与详情跳转；
- `/api/workbench3d/reset` 从工程 YAML 重载场景；
- 三维对象树覆盖阵列、观察面、目标区、保护区、反射面、孔缝、腔体和远场源；
- 属性面板只开放白名单字段，材料设置面板只开放归一化代理参数；
- 属性面板新增绝对量纲标定卡片，可输入 8x8 阵元功率矩阵和实测点 CSV，并显示 V3.0 导入数据桥接摘要，把结果写入资产台账产物；
- 三维视口移动模式支持目标区、保护区、孔缝和腔体的平面拖拽；
- 属性面板新增受控几何变换控件，可对支持字段的对象执行 0.1λ 平移、10% 缩放和 5° 旋转，并统一回到后端对象更新 API 做工程约束校验；
- 求解结果面板显示目标 RMSE、最低覆盖率、区外峰值、保护区超限、field_hash、V&V 适用性诊断和验收清单；
- 求解任务队列显示 `JOB-xxxx`、任务状态、绑定的 `SOL-xxxx`、scene_hash、field_hash 和关键摘要，任务详情可回写到当前三维视口；前端可触发审计、创建后台求解检查点、恢复已暂停任务、对已完成/失败任务生成重试任务、对排队中/运行中/已暂停任务发起取消请求，并在任务记录中保留操作日志；
- 三维视口可把 `结果图层` 渲染为半透明 heatmap，求解面板显示色标、峰值坐标、中心剖面采样和 x/y 剖面交互曲线，用于快速审计场分布；
- 求解面板把 `适用性` payload 渲染为 V&V 诊断区，显示得分、结论、传播后端、状态计数和需关注检查项，用于把三维工程求解结果纳入可信度审计；
- 对象级指标可在求解面板按目标区/保护区列出，点击指标行可选中对象，三维视口会在对应对象附近叠加状态徽标；
- 每次求解生成 `JOB-xxxx` 任务记录和 `SOL-xxxx` 结果档案，保存完整 JSON，并维护 `index.json`/`index.csv`/`audit.json`/`audit.csv` 轻量任务/结果索引；后台任务会把提交时 `CAEProject` 快照写入任务 JSON，暂停后恢复从该快照继续；服务启动时会扫描已有任务与结果并恢复列表，前端可列出、复查、重试、暂停、恢复、审计并导出单次求解结果；
- 统一工程资产台账汇总求解任务、求解结果、工程快照和导入标定桥接，输出 `workbench3d_assets/index.json`、`index.csv`、`assets.sqlite`、`audit.json`、`audit.csv`、`database_audit.json`、`database_audit.csv`、`lineage.json`、`lineage.csv`、`reproducibility_audit.json`、`reproducibility_audit.csv`、`absolute_calibration.json`、`absolute_calibration_points.csv`、`absolute_element_powers.csv`、`imported_calibration_bridge.json`、`imported_calibration_bridge.csv`、`naming_audit.json` 与 `naming_audit.csv`；SQLite 同时维护 `workbench3d_assets`、`workbench3d_solve_jobs`、`workbench3d_solve_job_events`、`workbench3d_results`、`workbench3d_snapshots` 和 `workbench3d_database_manifest` 表，前端可按类型/关键字筛选资产、触发审计、检查数据库事件行数、浏览任务/结果/快照库表、查看快照-任务-结果-重试的资产谱系、检查导入数据标定桥接 `IMP-CAL-001`、检查结果 JSON/哈希/JOB/SOL/V&V 记录可复查性、检查 `JOB/SOL/SNP` 编号和文件名哈希绑定，并从台账入口跳转到任务、结果、快照或导入桥接详情；
- 撤销/重做历史栈记录受控编辑；
- 工程快照可创建、列出、恢复和差异对比，并落盘为工程 YAML、场景 JSON、`index.json` 与 `index.csv`；服务启动时会扫描已有快照并恢复列表；
- 更新后自动调用 `CAEProject` 校验，禁止目标区、保护区、孔缝、腔体越界和材料代理越界；
- 场景 payload 包含 `scene_hash`、对象统计、模型边界和校验清单。

## 当前边界

这是 V2.0B 的工程原型，不是完整 CAD/CAE 建模器。当前编辑闭环支持属性面板、材料设置、绝对量纲标定、导入数据标定桥接、三维拖拽移动、受控几何变换控件、快速求解联动、求解任务队列、本地后台worker预览、任务暂停/恢复/取消/重试/审计、SQLite 任务事件表、观察面结果图层回写、V&V 适用性诊断、对象指标列表/三维徽标、求解结果档案、工程快照落盘/恢复/差异对比和统一工程资产台账筛选/审计/库表浏览/谱系追溯/复现审计/命名规范检查，三维视口支持选择、旋转、缩放、重置视图和 JSON 快照导出，求解面板可读出色标、峰值坐标、中心剖面采样、x/y 剖面交互曲线和对象级约束状态。材料编辑器仅修改归一化材料代理参数，不等价于全波材料库。求解联动复用平台已有波长尺度归一化快速求解器，不是 CST/HFSS/COMSOL 级全波求解。当前后台worker仍是单机本地线程预览，只服务归一化快速求解检查点；SQLite 仍是单机轻量数据库，资产谱系只表达归一化快照、JOB、SOL、导入桥接资产和本地事件日志关系，不代表真实设备状态继承；绝对量纲标定只表达用户输入功率元数据与实测点残差，导入数据桥接只表达外部样本、坐标归一化、代理模型残差和不确定度证据，不代表真实作用距离或器件阈值；资产命名规范仍是本地台账级审计而非工厂级数据库主键策略，几何变换控件仍是按钮式受控编辑而非完整三维拖拽 Gizmo，正式多用户调度器和正式工程数据库仍属于后续门槛。

平台仍保持公开科研安全边界：

- 核心快速求解使用波长尺度归一化几何；
- 允许把绝对功率作为实测标定元数据输入和审计；
- 不输出真实器件阈值；
- 不输出毁伤概率或现实作用距离；
- 不冒充 CST/HFSS/COMSOL 全波求解器。

## 验收接口

```text
GET  /api/workbench3d/scene
POST /api/workbench3d/objects/{object_id}
POST /api/workbench3d/materials/{material_id}
GET  /api/workbench3d/absolute-calibration
POST /api/workbench3d/absolute-calibration
POST /api/workbench3d/solve
POST /api/workbench3d/solve-jobs
GET  /api/workbench3d/solve-jobs
GET  /api/workbench3d/solve-jobs/audit
POST /api/workbench3d/solve-jobs/{job_id}/pause
POST /api/workbench3d/solve-jobs/{job_id}/resume
POST /api/workbench3d/solve-jobs/{job_id}/cancel
POST /api/workbench3d/solve-jobs/{job_id}/retry
GET  /api/workbench3d/solve-jobs/{job_id}
GET  /api/workbench3d/results
GET  /api/workbench3d/results/{result_id}
GET  /api/workbench3d/assets
GET  /api/workbench3d/assets/audit
GET  /api/workbench3d/assets/database
GET  /api/workbench3d/assets/database/records
GET  /api/workbench3d/assets/lineage
GET  /api/workbench3d/assets/reproducibility
GET  /api/workbench3d/assets/imported-calibration
GET  /api/workbench3d/assets/naming
GET  /api/workbench3d/assets/{asset_id}
POST /api/workbench3d/reset
GET  /api/workbench3d/history
POST /api/workbench3d/undo
POST /api/workbench3d/redo
GET  /api/workbench3d/snapshots
POST /api/workbench3d/snapshots
POST /api/workbench3d/snapshots/{snapshot_id}/restore
GET  /api/workbench3d/snapshots/{left_id}/diff/{right_id}
```

`GET /api/workbench3d/scene` 的关键字段：

```text
版本        V2.0B-preview
引擎        Three.js 0.166.1
对象        三维对象列表
材料库      可编辑材料代理列表
对象树      UI 对象树分组
统计        对象数量和启用数量
校验        后端几何与研究边界检查
scene_hash  场景结构哈希
绝对量纲标定 阵元功率元数据、实测点校准残差、不确定度和实测覆盖区间
导入数据标定桥接 V3.0 Measurement Campaign 桥接、模型误差对比和外部数据 V&V 审计摘要
```

`GET/POST /api/workbench3d/absolute-calibration` 的关键字段：

```text
阵元功率       每阵元输入功率元数据，数量必须匹配当前阵列
实测标定点     point_id、distance_m、normalized_model_amplitude、measured_field_v_per_m、uncertainty_percent
功率元数据     总输入功率、平均阵元功率、启用阵元数和功率不均衡
校准结果       校准系数、残差 RMSE、相对 RMSE、2sigma 覆盖率和实测距离覆盖区间
索引           absolute_calibration.json / absolute_calibration_points.csv / absolute_element_powers.csv
不输出项       真实作用距离、器件失效阈值、损伤/毁伤概率、阈值到距离反推
安全边界       只做实测点量纲标定，不做作用距离或器件阈值推断
```

`POST /api/workbench3d/solve` 的关键字段：

```text
scene_hash  与当前三维场景绑定的结构哈希
result_id   单次求解结果档案编号
求解任务     若通过任务队列提交，包含 JOB 编号、状态、时间戳和索引路径
求解器       快速求解配置和传播后端
摘要         目标RMSE、覆盖率、区外峰值、保护区超限、耗时
对象指标     目标区和保护区的对象级约束诊断，可驱动前端列表和三维徽标
结果图层     观察面归一化场强 dB 矩阵、色标、边界、统计、中心剖面、x/y 剖面曲线和 field_hash
适用性       归一化模型适用性检查，可驱动前端 V&V 诊断层
验收清单     联合控场、适用性和安全边界提示
结果档案     结果编号、保存路径、scene_hash、field_hash 和主要摘要
索引         index.json / index.csv 结果索引路径
```

`GET /api/workbench3d/solve-jobs` 的关键字段：

```text
任务         求解任务列表，包含 JOB 编号、状态、result_id、scene_hash、field_hash 和主要摘要
审计         任务id唯一性、索引文件、路径、重试链路和操作日志检查项
索引         index.json / index.csv / audit.json / audit.csv 任务索引路径
历史         与当前工程历史栈、快照和结果档案绑定的摘要
```

`POST /api/workbench3d/solve-jobs` 可选后台字段：

```text
background    为 true 时创建本地后台worker任务，默认 false 保持同步快速求解
start_paused  为 true 时任务以已暂停检查点创建，便于后续恢复或取消
```

`POST /api/workbench3d/solve-jobs/{job_id}/pause` / `resume` 的关键字段：

```text
操作         暂停或恢复动作、时间、是否通过和说明
任务         更新后的 JOB 任务记录
队列         更新后的任务列表
审计         更新后的任务生命周期审计
```

`POST /api/workbench3d/solve-jobs/{job_id}/retry` 的关键字段：

```text
操作         动作、时间、来源任务、新任务和是否通过
任务         新生成的 JOB 任务记录，包含重试来源
结果         新 JOB 绑定的 SOL 结果档案
队列         更新后的任务列表
审计         更新后的任务生命周期审计
```

`POST /api/workbench3d/solve-jobs/{job_id}/cancel` 的关键字段：

```text
操作         动作、时间、是否通过和说明；已完成任务返回不可取消但保留操作日志
任务         更新后的任务记录
队列         更新后的任务列表
审计         更新后的任务生命周期审计
```

`GET /api/workbench3d/snapshots` 的关键字段：

```text
快照         工程快照列表
索引         index.json / index.csv 快照索引路径
工程路径     可恢复的 CAEProject YAML
场景路径     可审计的三维场景 JSON
```

`GET /api/workbench3d/assets` 的关键字段：

```text
资产         统一资产列表，覆盖工程快照、求解任务和求解结果
资产id       SNP/JOB/SOL 编号
类型         工程快照、求解任务或求解结果
scene_hash   与三维场景绑定的结构哈希
field_hash   与求解结果图层绑定的场哈希
路径         资产主文件路径
辅助路径     关联结果、场景或工程文件路径
摘要         类型计数、状态计数、最新资产和缺失路径审计摘要
筛选         asset_type / q / limit 查询条件和匹配数量
审计         资产id唯一性、三类资产覆盖、索引文件和资产路径可复查检查项
资产谱系     SNP/JOB/SOL 节点、快照到任务的同 scene_hash 基线、任务到结果、重试派生和事件派生关系
复现审计     SOL 结果的 JSON 路径、哈希、JOB 绑定、谱系边和 V&V 记录可复查性
绝对量纲标定 阵元功率元数据、实测点校准残差和不确定度产物
命名审计     JOB/SOL/SNP 编号、标签、scene_hash/field_hash 文件名绑定和资产id全局唯一检查
索引         index.json / index.csv / assets.sqlite / audit.json / audit.csv / database_audit.json / database_audit.csv / lineage.json / lineage.csv / reproducibility_audit.json / reproducibility_audit.csv / absolute_calibration.json / absolute_calibration_points.csv / absolute_element_powers.csv / naming_audit.json / naming_audit.csv 台账索引路径
安全边界     资产的归一化模型适用边界
```

`GET /api/workbench3d/assets/database` 的关键字段：

```text
数据库审计     SQLite 数据库完整性、核心表、资产/任务/事件/结果/快照行数和关联检查
任务事件       从 JOB 操作日志展开的提交、导入、重试、取消等事件行
行数           workbench3d_assets、workbench3d_solve_jobs、workbench3d_solve_job_events、workbench3d_results、workbench3d_snapshots 与 manifest 表行数
最新任务事件   最近一次任务事件摘要
索引           assets.sqlite / database_audit.json / database_audit.csv 路径
安全边界       单机归一化工程资产数据库，不代表真实设备任务数据库
```

`GET /api/workbench3d/assets/database/records` 的关键字段：

```text
数据库路径     assets.sqlite 路径
表             当前返回的 SQLite 表名；可用 table 查询参数限制到单表
limit          每张表最多返回的样例记录数
行数           每张表总行数
结构           PRAGMA table_info 展开的列名、类型、非空和主键信息
记录           资产、任务、任务事件、结果、快照和 manifest 的样例行
审计           同一数据库的完整性验收结果
安全边界       只浏览归一化工程资产数据库，不代表真实设备数据库
```

`GET /api/workbench3d/assets/lineage` 的关键字段：

```text
节点           SNP/JOB/SOL 谱系节点，包含类型、状态、时间、scene_hash、field_hash 和路径
边             快照到任务的同 scene_hash 基线、任务到结果的生成结果、任务到任务的重试/事件派生关系
摘要           节点数、边数、快照数、任务数、结果数、任务结果边、重试派生边和同场景基线边
异常           任务缺失结果、结果缺失任务、重试来源异常和缺少 scene_hash 的节点
验收清单       节点唯一性、任务结果边、结果任务边、重试来源和 scene_hash 覆盖检查
索引           lineage.json / lineage.csv 路径
安全边界       谱系只表达归一化工程资产与本地事件日志关系，不代表真实设备状态继承
```

`GET /api/workbench3d/assets/reproducibility` 的关键字段：

```text
结果复现记录   SOL 结果的 JSON 路径、scene_hash、field_hash、JOB 绑定、谱系边和 V&V 记录检查
摘要           结果数、可复查结果数、队列结果数、直接求解结果数和任务结果边数量
异常           缺失结果路径、缺失哈希、任务关联异常、谱系边异常和 V&V 记录缺失
验收清单       结果 JSON、哈希、JOB 回溯、谱系边和 V&V 记录检查
索引           reproducibility_audit.json / reproducibility_audit.csv 路径
安全边界       只证明归一化快速求解结果可复查，不代表真实设备实验复现
```

`GET /api/workbench3d/assets/naming` 的关键字段：

```text
命名审计       编号规则、文件名规则、统计、问题列表和验收清单
命名规则       JOB/SOL/SNP 编号、任务/结果/快照文件名和哈希绑定规则
统计           任务数、结果数、快照数、资产数、路径检查数和问题数
命名问题       编号、标签、路径或哈希绑定不符合规范的记录
索引           naming_audit.json / naming_audit.csv 路径
安全边界       本地归一化工程资产命名审计，不代表真实设备数据库编号体系
```

`GET /api/workbench3d/snapshots/{left_id}/diff/{right_id}` 的关键字段：

```text
左快照       左侧快照索引记录
右快照       右侧快照索引记录
scene_hash_changed  两份归一化场景结构哈希是否变化
摘要         对象差异数、材料差异数、字段变更数
对象差异     按对象 id 聚合的新增/删除/字段变更列表
材料差异     按材料 id 聚合的字段变更列表
安全边界     仅比较工程参数和归一化代理字段，不代表实物状态或全波仿真差异
```

## 后续门槛

- 增加真正三维拖拽式尺寸和旋转 Gizmo，并继续映射到同一个受控更新 API；
- 把当前本地资产命名审计扩展为工厂级命名策略，并把 SQLite 资产/事件表继续迁移为正式工程数据库；
- 把当前单机后台worker预览迁移为正式多用户调度器，并补正式工程/结果数据库管理；
- 增加 VTK/体数据查看路线，服务于 V3.0 外部仿真数据导入。
