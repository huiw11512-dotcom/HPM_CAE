"""HPM-DT 平台最高层目标与路线图元数据。"""
from __future__ import annotations

PLATFORM_NORTH_STAR = (
    "持续演进 HPM-DT（High-Power Microwave Digital Twin），构建一个面向高功率微波相控阵、"
    "效应分析与数字孪生研究的全中文任务级科研 CAE 平台。所有版本开发都必须服务于这个长期目标，"
    "而不是孤立地增加功能。"
)

PLATFORM_POSITIONING = (
    "HPM-DT 不是算法仓库、单个论文项目或脚本集合，而是高功率微波任务级数字孪生 CAE 平台。"
)

PRODUCT_ROUTE = (
    "V2.0B 以后采用 Scene First：默认首页是三维场景编辑，可信度验证作为工具入口；"
    "V2.0C 转向 Mission First 任务级仿真框架，V2.0D 转向 Publication First 论文自动生产线。"
)

PLATFORM_LAYERS = (
    "物理建模层 Physics Layer",
    "感知层 Perception Layer",
    "防护层 Protection Layer",
    "控场层 Field Control Layer",
    "效应层 Effect Layer",
    "可信度层 Verification & Validation Layer",
    "CAE平台层 Workbench Layer",
    "论文生产层 Publication Layer",
)

PLATFORM_ROADMAP = (
    "V2.0A 可信度验证体系",
    "V2.0B 三维场景编辑器（Scene First）",
    "V2.0C 任务级仿真框架（Mission First，Plugin Marketplace 作为基础设施）",
    "V2.0D 论文自动生产线（Publication First / Paper Factory）",
    "V2.1 数字孪生任务库",
    "V3.0 真实数据接入与实验闭环：CST/HFSS/测量数据/CSV/Touchstone/HDF5",
    "V4.0 HPM 数字孪生平台",
)

PLATFORM_LAYER_STATUS = (
    {
        "层级": "物理建模层",
        "英文": "Physics Layer",
        "职责": "阵列、传播、多径、孔缝、腔体、近场、远场、材料",
        "当前状态": "基础可用，V3.0 数据导入预览接入中",
        "当前证据": "已有 RectangularArray、自由空间/镜像/孔缝腔体/混合传播后端、材料/几何对象，以及 CST/HFSS 导出包、测量批次、CSV/Touchstone/NPZ/HDF5 外部数据导入审计层、CalibrationSamples 桥接预览、代理模型误差对比预览、外部数据 V&V 预评分审计和证据包 V&V 候选评分。",
        "下一步": "把通过候选评分的数据包推进到真实源链/相位参考复核、正式可信度评分纳入和三维工作台结果查看。",
    },
    {
        "层级": "感知层",
        "英文": "Perception Layer",
        "职责": "DOA、MUSIC、ESPRIT、CNN、Transformer、目标识别",
        "当前状态": "阵列测向可用，外部观测数据接口预览接入中",
        "当前证据": "已有 MUSIC、ESPRIT、PAWR-MUSIC、测向基准验证和 V3.0 外部数据格式/测量批次审计接口。",
        "下一步": "增加真实数据导入后的感知基准、标定桥接样本复核、测量不确定度传播和学习模型接口。",
    },
    {
        "层级": "防护层",
        "英文": "Protection Layer",
        "职责": "MVDR、LCMV、宽零陷、鲁棒波束形成、动态防护",
        "当前状态": "基础可用",
        "当前证据": "已有 MVDR、LCMV、宽零陷、鲁棒波束形成和约束残差验证。",
        "下一步": "把动态防护策略接入三维工作台和批量实验。",
    },
    {
        "层级": "控场层",
        "英文": "Field Control Layer",
        "职责": "区域赋形、多目标控场、RIS、协同阵列、鲁棒优化",
        "当前状态": "区域控场可用",
        "当前证据": "已有区域赋形、多目标控场、功放/DPD 和鲁棒优化流程。",
        "下一步": "补 RIS、协同阵列和三维对象级控制交互。",
    },
    {
        "层级": "效应层",
        "英文": "Effect Layer",
        "职责": "剂量、风险、概率、敏感度、数字孪生",
        "当前状态": "代理模型可用",
        "当前证据": "已有归一化剂量、风险、概率和效应数字孪生代理输出。",
        "下一步": "把效应代理纳入统一 V&V 和论文流水线。",
    },
    {
        "层级": "可信度层",
        "英文": "Verification & Validation Layer",
        "职责": "解析验证、文献复现、不确定度、适用性、可信度评分",
        "当前状态": "V2.0A 已完成",
        "当前证据": "已有 6 类自动 V&V、Monte Carlo、不确定度、敏感性、可信度评分、外部数据残差/不确定度预评分审计和证据包 V&V 候选评分。",
        "下一步": "补外部文献 DOI、正式复现实验编号、真实源链/相位参考人工复核和真实数据导入后的正式评分纳入。",
    },
    {
        "层级": "CAE平台层",
        "英文": "Workbench Layer",
        "职责": "项目、建模、求解、结果、报告、数据库",
        "当前状态": "V2.0B Scene First 三维原型与 V2.0C 任务级仿真基础设施接入中",
        "当前证据": "已有 FastAPI + Bootstrap 工作台，默认首页已切换为场景编辑；V2.0B Three.js 本地三维视口、对象树、属性面板、材料设置、材料代理审计、拖拽移动、求解联动、观察面结果图层回写、色标与中心剖面读数、求解结果档案、轻量结果索引、撤销重做、工程快照落盘恢复、受控更新 API，以及 V2.0C 本地插件目录、启停、白名单运行和验收 API。",
        "下一步": "补尺寸/旋转 Gizmo、任务时间线、任务模板、快照差异对比、求解任务队列、正式工程/结果数据库管理和更多任务级插件类型。",
    },
    {
        "层级": "论文生产层",
        "英文": "Publication Layer",
        "职责": "实验、统计、图表、LaTeX、IEEE模板、论文自动生成",
        "当前状态": "V2.0D Paper Factory 预览接入中",
        "当前证据": "已有 HTML 报告、论文图包、LaTeX 表格、论文提纲、Notebook，以及 V2.0D 自动论文草稿、IEEE骨架、IEEE/期刊/学位论文多模板、插件模板合并、BibTeX 引用库、文献复现注册表、统计审计、模板审计、LaTeX 编译审计、图表清单、补充材料索引和论文包 ZIP。",
        "下一步": "补外部 DOI 绑定、真实授权数据统计显著性报告、外部目标期刊模板签名和本机 PDF 编译归档。",
    },
)

PLATFORM_MILESTONE_STATUS = (
    {
        "阶段": "V2.0A",
        "名称": "可信度验证体系",
        "状态": "已完成",
        "验收证据": "6/6 V&V 用例通过；可信度评分 91.58/A；全量 pytest 通过。",
        "下一门槛": "扩展文献复现和真实数据校准用例。",
    },
    {
        "阶段": "V2.0B",
        "名称": "三维场景编辑器（Scene First）",
        "状态": "进行中",
        "验收证据": "默认首页已切换为场景编辑，首屏展示场景/对象/任务/结果；已接入 Three.js 本地视口、对象树、属性面板、材料设置、材料代理审计、拖拽移动、求解联动、观察面结果图层回写、色标与中心剖面读数、求解结果档案、轻量结果索引、撤销重做、工程快照落盘恢复和后端几何/材料校验 API。",
        "下一门槛": "完成尺寸/旋转 Gizmo、快照差异对比、正式工程/结果数据库管理、求解任务队列和场景首页浏览器验收。",
    },
    {
        "阶段": "V2.0C",
        "名称": "任务级仿真框架（Mission First）",
        "状态": "预览接入中",
        "验收证据": "已有本地 JSON manifest、语义版本校验、启停 API、参数 Schema、白名单 builtin_hook、Plugin Marketplace 页面、五个内置插件运行审计和论文模板插件协议，可作为任务模板、传播后端、感知/控场模块的基础设施。",
        "下一门槛": "补任务场景时间线、目标运动、感知-测向-控场-风险评估闭环、任务模板库、插件级 V&V、外部插件包签名/沙箱和工作台求解器联动。",
    },
    {
        "阶段": "V2.0D",
        "名称": "论文自动生产线（Publication First / Paper Factory）",
        "状态": "预览接入中",
        "验收证据": "已有 PaperFactoryService、生成 API、下载端点、UI 入口、Markdown 论文草稿、IEEE LaTeX 骨架、IEEE/期刊/学位论文多模板、插件模板合并、BibTeX 引用库、文献复现注册表、统计审计、模板审计、LaTeX 编译审计、图表清单、补充材料索引和可复现论文包 ZIP。",
        "下一门槛": "补实验设计器、外部 DOI 绑定、真实授权数据证据链、外部目标期刊模板签名和本机 PDF 编译归档。",
    },
    {
        "阶段": "V2.1",
        "名称": "数字孪生任务库",
        "状态": "路线图阶段",
        "验收证据": "待沉淀可复用任务模板、场景库、结果库和任务级对比基准。",
        "下一门槛": "定义教学场景、论文复现场景、验收场景和任务级结果索引。",
    },
    {
        "阶段": "V3.0",
        "名称": "真实数据接入与实验闭环",
        "状态": "预览接入中",
        "验收证据": "已有 DataImportService、CST/HFSS 导出包识别、Measurement Campaign 测量批次识别、CSV/Touchstone/NPZ/HDF5 格式识别、单位/坐标列审计、工程元数据预览、仪器链/校准/不确定度审计、mm 到 lambda 坐标规范化预览、标定准备度报告、CalibrationSamples 标定桥接预览、代理模型误差对比预览、外部数据 V&V 预评分审计、每阵元功率/实测标定点证据包模板、正式证据包审计、证据包 V&V 候选评分、样例目录、路径解析 API 和工作台数据导入页面。",
        "下一门槛": "用真实授权数据把候选评分中的残差和 2σ 覆盖率打到正式门槛内，再完成人工复核、正式可信度评分纳入和授权外部数据标定报告。",
    },
    {
        "阶段": "V4.0",
        "名称": "HPM 数字孪生平台",
        "状态": "长期目标",
        "验收证据": "需要软件著作权材料、SCI 论文体系、项目申报材料和实验室公共平台工程。",
        "下一门槛": "形成稳定平台白皮书、演示工程和实验室复用流程。",
    },
)


def platform_north_star_payload() -> dict[str, object]:
    return {
        "平台名称": "HPM-DT",
        "平台全称": "High-Power Microwave Digital Twin",
        "最高层目标": PLATFORM_NORTH_STAR,
        "平台定位": PLATFORM_POSITIONING,
        "产品路线": PRODUCT_ROUTE,
        "默认首页": "场景编辑",
        "验证中心入口": "工具 -> 可信度验证",
        "用户主链路": ["建立场景", "配置阵列与系统", "运行任务", "查看场分布与风险", "导出论文"],
        "八层架构": list(PLATFORM_LAYERS),
        "阶段路线": list(PLATFORM_ROADMAP),
        "层级状态": [dict(item) for item in PLATFORM_LAYER_STATUS],
        "里程碑状态": [dict(item) for item in PLATFORM_MILESTONE_STATUS],
        "当前里程碑": "V2.0A 可信度验证体系",
        "关键文档": {
            "North Star": "docs/HPM_DT_NORTH_STAR.md",
            "长期路线图": "docs/HPM_DT_ROADMAP.md",
            "Codex协作说明": "AGENTS.md",
        },
    }
