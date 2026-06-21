# 论文输出映射

平台共享同一阵列、信号、随机种子、配置系统和统计评价，不为每篇论文复制一套模型。

## 论文线1：相干多径与局部通道异常下的阵列感知

V0.3已形成可运行主体：FBSS、二维ESPRIT、BTTB基线、PAWR、四类扫参、消融和统计检验。

- 工作稿：`paper1_perception_v03_outline.md`
- 技术说明：`../docs/PERCEPTION_V03.md`
- 图文报告：`../outputs_v03_perception/perception_v03_report_standalone.html`

稳妥定位是“利用宽松环境先验提升局部通道异常下的相干多径稳定性，并量化先验失配边界”，而不是宣称全面优于所有网格无关方法。

## 论文线2：DOA不确定条件下的接收防护

V0.4已形成可运行主体：方向漂移协议、Point/Derivative LCMV、Sector-MVDR、CR-HybridNull、五类扫参、配对统计和消融。

- 工作稿：`paper2_protection_v04_outline.md`
- 技术说明：`../docs/PROTECTION_V04.md`
- 图文报告：`../outputs_v04_protection/protection_v04_report_standalone.html`

当前可支持的主张是：置信域角流形可以显著改善点零陷和导数零陷在方向漂移下的稳定性；与软扇区MVDR相比存在均值优势，但快速配置的显著性处于边界，必须完成论文级复算。


## 论文线2升级：动态感知—防护闭环

V0.5在V0.4基础上加入PAWR二维DOA协方差、时间戳Kalman传播、多干扰运动、处理滞后和通道故障，形成PCP-HybridNull动态闭环。

- 工作稿：`paper2_dynamic_closed_loop_v05_outline.md`
- 技术说明：`../docs/CLOSED_LOOP_V05.md`
- 图文报告：`../outputs_v05_closed_loop/closed_loop_v05_report_standalone.html`

快速配置可支持的谨慎主张是：传播后的感知协方差能够在多源运动和滞后条件下自适应生成角域覆盖；相对固定扇区存在约1 dB的配对平均优势，但仍有速度、更新间隔和置信域饱和边界。

## 论文线3：归一化响应约束的空间场调控

核心插件：`field_control/`、`physics/effect_model.py`、`evaluation/`。公开版只研究归一化场均匀性、旁区响应和鲁棒优化，不进行真实设备损伤推断。

## 统一实验规范

- 定稿结果每点至少100次随机试验，或给出样本量论证；
- 同时报均值、置信区间、失败率、WNG与运行时间；
- 超参数在独立开发集选择，禁止在最终测试曲线上调参；
- 至少一个强基线和一个结构化/扇区基线；
- 主动报告先验、模型、阵列失配和置信域越界的失效边界；
- 所有图表由配置和脚本自动生成，禁止手工改数据。

## 论文线3升级：不确定条件下的近场区域鲁棒赋形

V0.6已形成可运行主体：旋转扩展目标区、Point-Focus、Region-LS、Nominal-PGMS、SR-PGMS-DPD、四类不确定性扫参、Pareto前沿和组件消融。

- 工作稿：`paper3_field_control_v06_outline.md`
- 技术说明：`../docs/FIELD_CONTROL_V06.md`
- 图文报告：`../outputs_v06_field_control/field_control_v06_report_standalone.html`

当前可支持的谨慎主张是：场景训练与有界DPD能够提高目标均匀性、覆盖率和旁区峰值联合满足率；Point-Focus仍有能量效率优势，Nominal-PGMS仍可能在部分旁区统计量上更优，因此必须以Pareto折中而非“全面领先”组织论文。
