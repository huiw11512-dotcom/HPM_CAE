# V3.0 数据导入预览

V3.0 的目标是让 HPM-DT 从纯归一化公开模型扩展为可导入外部仿真和测量数据的科研平台。当前实现是第一阶段预览，重点是 CST/HFSS 导出包识别、测量批次识别、通用数据格式识别、元数据、单位、坐标列、不确定度、校准状态、复数值和数据血缘审计。

## 当前能力

- 入口模块：`src/hpm_platform/data_import/importers.py`
- 样例目录：`outputs_v20a_vv/data_import_v30/samples/`
- UI 页面：V2.0A 工作台“数据导入”
- API：

```text
GET  /api/data-import/catalog
GET  /api/data-import/acceptance
GET  /api/data-import/calibration-readiness
GET  /api/data-import/calibration-bridge
GET  /api/data-import/model-comparison
GET  /api/data-import/vv-audit
GET  /api/data-import/samples/{sample_id}
POST /api/data-import/inspect
```

## 支持格式

| 格式 | 当前解析能力 |
|---|---|
| CSV | 列名、记录数、坐标列、单位、复数字段配对、前 5 行预览 |
| Touchstone | `.sNp` 端口数、频点数、选项行、频率单位、参数格式、参考阻抗 |
| NPZ | 数组名称、形状、dtype、复数标记、坐标数组和单位 |
| HDF5 | HDF5 签名识别；若环境安装 `h5py`，进一步列出数据集形状和 dtype |
| CST | `.cst` 或导出包/目录的元数据预览、结果文件清单、S 参数/场数据线索、单位和坐标系审计 |
| HFSS | `.aedt`/`.aedtz`/`.hfss` 或导出包/目录的元数据预览、报告文件清单、S 参数/远场数据线索、单位和坐标系审计 |
| MeasurementCampaign | 带 `MEASUREMENT_CAMPAIGN.json` 的 zip/目录，审计批次、仪器链、校准状态、不确定度模型、数据血缘和测量文件清单 |

## 标定准备度

当前预览新增 `calibration_readiness.json`，用于判断导入数据是否具备进入 V&V 标定流程的前置条件。它会检查：

- 是否存在可审计单位；
- 是否可把 `x/y/z_mm`、`x/y/z_lambda` 或角度坐标规范化；
- 是否存在可配对的归一化复场实部/虚部；
- 测量批次是否包含不确定度模型和校准状态；
- 是否保留 SHA256、数据血缘和安全边界。

Measurement Campaign 样例会把 `x_mm/y_mm/z_mm` 按 `reference_frequency_ghz` 转换为 `x_lambda/y_lambda/z_lambda` 预览，并统计已进入 `CalibrationSamples` 桥接预览的归一化复场样本数。

## 标定桥接预览

当前版本新增 `calibration_bridge_report.json`，用于证明 Measurement Campaign 中已经规范化的近场复数样本可以被构造成 `backend_calibration.CalibrationSamples`：

- 读取 `measurement_campaign_bundle.zip` 中的 `MEASUREMENT_CAMPAIGN.json` 和 `measurements/near_field_scan.csv`；
- 按 `reference_frequency_ghz` 把 `x_mm/y_mm/z_mm` 转换为 `x_lambda/y_lambda/z_lambda`；
- 提取 `E_real_norm/E_imag_norm` 作为归一化复场参考样本；
- 使用当前 `CAEProject` 传播后端生成代理 `focus_weights` 激励，只用于接口 smoke preview；
- 调用 `calibrate_backend_scales` 生成标定预览字段，包括拟合尺度、RMSE 前后对比和求解状态。

桥接报告只说明“导入数据形状已经能进入 V&V 标定接口”。它不是真实测量标定闭环，代理激励不能替代实测源、馈电链、相位参考或绝对功率标定。

## 模型误差对比预览

当前版本新增 `model_comparison_report.json`，把同一批 Measurement Campaign 归一化复场样本与当前工程代理激励降阶传播模型做误差对比：

- 复用 `CalibrationSamples` 桥接样本和 `calibrate_backend_scales` 的初始/拟合场；
- 输出标定前后 RMSE、相对 RMSE、MAE、p95 残差、最大残差和拟合尺度；
- 读取 `amplitude_sigma_norm` 和 `phase_sigma_deg`，合成为复场残差 sigma；
- 输出逐点残差、归一化残差和 1σ/2σ 覆盖率；
- 显式保留“真实源链与相位参考已接入 = false”的门槛，避免把代理激励预览误解为真实标定。

该报告只证明外部测量批次已经能进入“导入样本 -> 标定接口 -> 模型残差 -> 不确定度覆盖率”的软件闭环。真实 V&V 结论仍需要授权外部数据、真实馈电链/相位参考、误差模型和独立复核。

## 外部数据 V&V 可信度审计

当前版本新增 `external_data_vv_audit.json`，把模型误差对比报告进一步传播为 V&V 风险审计：

- 输出外部数据预评分、预评分等级和分项得分；
- 把标定后相对 RMSE、2σ 覆盖率、中位归一化残差等指标整理为关键指标；
- 显式判断“可纳入正式可信度评分”，当前代理激励预览因真实源链/相位参考未接入而保持 `false`；
- 给出风险调整预览评分，但在不满足正式门槛时不改写 V2.0A 核心可信度评分；
- 输出风险信号和门槛表，便于论文工厂和工作台复用同一份审计证据。

该审计完成了“测量不确定度向 V&V 评分传播”的预览链路，但仍不构成真实实验结论。正式纳入评分需要真实源链、相位参考、授权数据、误差模型和独立复核同时满足门槛。

## 内置样例

| 样例 ID | 文件 | 说明 |
|---|---|---|
| `V30-CSV-NEAR-FIELD` | `near_field_probe.csv` | 波长归一化近场复值采样 |
| `V30-TOUCHSTONE-S2P` | `coupler_response.s2p` | 2 端口归一化 S 参数 |
| `V30-NPZ-FIELD` | `field_volume.npz` | 复场数组包 |
| `V30-HDF5-STUB` | `external_measurement_stub.h5` | HDF5 样例或签名桩 |
| `V30-CST-EXPORT` | `cst_array_export_bundle.zip` | CST 导出包预览，含近场 CSV 和 S2P 结果 |
| `V30-HFSS-EXPORT` | `hfss_array_export_bundle.zip` | HFSS/AEDT 导出包预览，含 S2P 报告和远场 CSV |
| `V30-MEASUREMENT-CAMPAIGN` | `measurement_campaign_bundle.zip` | 测量批次预览，含 manifest、近场扫描 CSV、VNA S2P 和校准摘要 |

## 安全边界

导入层只做格式、单位、坐标系、复数值和数据血缘审计。不把外部数据自动解释为真实源功率、器件阈值、现实作用距离或真实毁伤概率。任何外部仿真或测量数据进入模型结论前，都必须补充来源、授权、单位换算、误差模型、适用边界和 V&V 标定。

## 下一步

- 使用真实源链、相位参考和授权实验/仿真数据替换当前代理激励预览；
- 把外部数据 V&V 审计推进为正式可信度评分输入；
- 把外部数据误差审计结果接入三维工作台结果查看。
