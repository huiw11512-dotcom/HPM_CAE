# HPM 数字化电磁算法 CAE V1.4 技术说明

## 1. 版本定位

V1.4 将 V1.3 的插件式传播模型与多对象控场能力，整合进一个全中文、本地离线的 CAE 工作台。本版重点不是新增某一种赋形算法，而是补齐数值研究中最容易被忽略的两层：

1. **模型适用性诊断**：明确当前参数是否处于降阶模型可解释的数值范围；
2. **传播后端参数标定**：利用归一化复场样本联合标定直达、反射和腔体分量尺度，并输出标定前后残差。

平台仍坚持以下研究边界：仅处理波长尺度几何、归一化标量复场、相对阵列响应和无量纲代理评价，不输出绝对源功率、现实器件阈值、毁伤概率或作用距离。

## 2. 本地启动

```bash
python -m pip install -r requirements.txt
python run_ui_v14.py
```

浏览器地址：

```text
http://127.0.0.1:7860
```

指定工程或端口：

```bash
python run_ui_v14.py --project configs/cae_project_v14.yaml --port 7861
```

## 3. 开源界面模板

V1.4 的 Web 界面采用：

- FastAPI：本地服务与结构化接口；
- Jinja2：页面模板；
- Bootstrap 5.1.1 官方 Dashboard 示例结构：导航、响应式网格、卡片与表单；
- Bootstrap Icons：操作图标；
- Plotly.js：离线交互图形。

前端资源全部随项目本地化，不调用公共 CDN。许可证与来源见 `THIRD_PARTY_NOTICES.md`。`dashboard.css` 只补充 CAE 图表高度、指标卡和中文表格等业务细节，不重新自绘一套后台皮肤。

## 4. 工作台页面

### 4.1 工程总览

自动加载默认工程并执行快速求解，集中显示：

- 三维场景；
- 观察面归一化场分布；
- 目标区总体 RMSE；
- 最低对象覆盖率；
- 区外峰值及约束状态；
- 当前传播后端适用性得分；
- 对象级约束结果。

### 4.2 静态控场求解

可选择四种传播后端和五类控场求解器，修改直达、反射、腔体三个归一化尺度后重新求解。页面同步更新场分布、约束裕量和阵元复权值。

### 4.3 传播后端对比

同一工程、同一快速求解配置下依次运行：

1. 自由空间标量格林；
2. 一阶镜像射线；
3. 孔缝—腔体降阶模型；
4. 混合场景后端。

输出场分布对照、目标区 RMSE、最低覆盖率、区外峰值、保护区超限和运行耗时。该对比用于揭示模型结构差异，不用于宣称某个降阶模型等价于全波求解。

### 4.4 模型适用性诊断

诊断器检查以下项目：

- 最大阵元间距与栅瓣风险；
- 阵列孔径、观察距离和近远场区间；
- 观察面网格步长；
- 标量复场研究边界；
- 一阶镜像反射的几何复杂度；
- 反射材料幅相与粗糙度代理；
- 孔缝电尺寸；
- 腔体品质因数；
- 腔体电尺寸；
- 模态截断数量。

每项状态为“适用、提示、谨慎、越界”，综合得分仅表示当前归一化数值模型的适用程度，不是物理真实性认证。

### 4.5 传播尺度参数标定

混合传播矩阵写成：

\[
H(\mathbf r)=\alpha_d H_d(\mathbf r)+\alpha_r H_r(\mathbf r)+\alpha_c H_c(\mathbf r),
\]

其中三个尺度分别对应直达、镜像反射和孔缝—腔体降阶分量。标定器将复场实部和虚部拼接为残差向量，通过带边界的 Soft-L1 鲁棒最小二乘估计三个尺度。输出：

- 初始尺度与标定尺度；
- 标定前后复场 RMSE；
- 标定前后 R²；
- 残差收敛曲线；
- 参考场、标定前残差和标定后残差空间图。

默认样本为平台生成的合成归一化复场。V3.0 已提供 Measurement Campaign 到 `CalibrationSamples` 的桥接预览；进入真实标定闭环前仍必须统一坐标、相位参考、源链和归一化规则。

## 5. 中文机理图库

V1.4 已将以下图形作为正式资源嵌入 UI 和验收报告：

- `01_全链路数字孪生架构图.png/.svg`
- `02_混合传播后端机理图.png/.svg`
- `03_传播后端参数标定闭环图.png/.svg`

当前会话没有开放 image2 图像生成工具，因此这些图由本地 Python/Matplotlib 生成，并保留可编辑 SVG。项目没有将其冒充为 image2 产物。图形生成脚本为 `scripts/generate_v14_illustrations.py`，可重复执行。

## 6. 关键代码入口

```text
run_ui_v14.py
configs/cae_project_v14.yaml
src/hpm_platform/ui/app_v14.py
src/hpm_platform/ui/v14_service.py
src/hpm_platform/ui/templates_v14/index.html
src/hpm_platform/ui/static_v14/
src/hpm_platform/validation/model_validity.py
src/hpm_platform/validation/backend_calibration.py
src/hpm_platform/validation/visualization.py
scripts/generate_v14_illustrations.py
scripts/build_v14_acceptance.py
```

## 7. 接口

本地服务提供：

```text
GET  /api/health        健康检查
GET  /api/overview      总览和快速求解结果
POST /api/solve         静态控场求解
POST /api/compare       传播后端对比
POST /api/validity      模型适用性诊断
POST /api/calibrate     传播尺度参数标定
```

接口文档：

```text
http://127.0.0.1:7860/接口文档
```

## 8. 验收产物

执行：

```bash
PYTHONPATH=src python scripts/build_v14_acceptance.py
```

生成：

- `outputs_v14_ui/v14_验收报告.html`
- `outputs_v14_ui/适用性诊断汇总.csv`
- `outputs_v14_ui/传播后端对比.csv`
- `outputs_v14_ui/参数标定结果.csv`
- `outputs_v14_ui/参数标定摘要.json`
- `outputs_v14_ui/验收指标.json`
- `outputs_v14_ui/CHECKSUMS.sha256`

## 9. 后续版本建议

V1.5 建议从“标定”继续推进到“验证数据管理”：支持外部归一化复场 CSV/NPZ 导入、训练/验证点分离、参数置信区间、自助法不确定性和多频点联合标定。这样可以把纯数值平台进一步变成可审计的模型验证平台，而不是只展示单次最优结果。
