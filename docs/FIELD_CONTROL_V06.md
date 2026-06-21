# V0.6：不确定条件下的归一化近场区域调控

## 1. 研究问题

V0.6把平台从接收端动态防护推进到发射端空间场调控。研究问题限定为：在标量近场模型、阵元幅相误差、控制平面配准抖动和无记忆功放非线性同时存在时，如何让一个二维目标区域的**归一化场幅值**接近给定设定值，同时抑制保护间隔之外的旁区暴露。

本模块不计算绝对功率、射程、真实设备阈值或毁伤概率。所有幅值、功放饱和点和成功门限均为无量纲算法压力测试参数。

## 2. 几何与场算子

- 阵列：8×8矩形面阵，半波长间距；
- 控制平面：`z = 8λ`，处于Fresnel区算法测试范围；
- 目标区：中心偏轴、旋转25°的椭圆；
- 保护间隔：椭圆归一化半径1到1.45之间，不参与旁区惩罚；
- 场模型：

\[
G_{pm}=\frac{\exp(-j k R_{pm})}{R_{pm} G_\mathrm{ref}},
\qquad
E_p=\sum_{m=1}^{M}G_{pm}w_m.
\]

`G_ref`取单位阵元RMS的相位共轭点聚焦在目标中心的场幅值，因此结果是无量纲相对场量。

## 3. 四种主方法

### Point-Focus

相位共轭聚焦到目标中心，再用一个正实标量最小化目标区幅值与设定值的平方误差。它的优点是实现简单、采样平面能量效率高；缺点是对扩展区域的均匀性和旁区峰值没有显式约束。

### Region-LS

以Point-Focus产生的目标区相位为模板，求解带旁区二次惩罚的复数岭回归：

\[
\min_w \|G_t w-d_t\|_2^2+
\lambda_o\|G_o w\|_2^2+\mu\|w\|_2^2.
\]

它能显著降低目标区空间波动，但固定复相位模板和名义模型限制了其不确定性鲁棒性。

### Nominal-PGMS

在名义场矩阵上直接优化幅值，而不是固定复相位：

\[
J_t=\frac{1}{N_ta_0^2}
\sum_{p\in\Omega_t}\left(|E_p|-a_0\right)^2,
\]

\[
J_o=\frac{1}{N_oa_0^2}
\sum_{p\in\Omega_o}
\max\left(|E_p|-\tau,0\right)^2.
\]

采用复数Adam更新，并在每次迭代后投影到阵元峰值和阵元RMS约束集合。

### SR-PGMS-DPD

所提方法在多个随机场景上最小化平均幅值损失：

\[
\min_w\frac{1}{S}\sum_{s=1}^{S}
\left[J_t^{(s)}(w)+\lambda_oJ_o^{(s)}(w)\right]
+\mu\frac{\|w\|_2^2}{M},
\]

其中每个场景同时扰动阵元增益、阵元相位和控制平面横向配准。优化输出被解释为期望的PA输出权值，再通过Rapp AM/AM与有界AM/PM模型的数值逆映射生成预失真驱动。

## 4. 功放非线性与预失真

Rapp AM/AM模型为：

\[
A_\mathrm{out}=\frac{A_\mathrm{in}}
{\left[1+(A_\mathrm{in}/A_\mathrm{sat})^{2p}\right]^{1/(2p)}}.
\]

AM/PM采用有界单调曲线，仅用于观察阵元相位随驱动幅度变化时的场图畸变。DPD使用逐阵元二分法反演可达幅值，并预旋转AM/PM相位；超过驱动上限的期望输出被裁剪。

## 5. 统一评价指标

- 目标区RMSE：`sqrt(mean((|E|-a0)^2))/a0`；
- 目标区CV：目标区幅值标准差除以均值；
- ±10%覆盖率：落入设定值±10%的目标区采样点比例；
- 旁区峰值和95分位值：相对目标设定值的dB值；
- 旁区高暴露面积：超过−6 dB或−10 dB门限的旁区面积比例；
- 采样平面能量效率：目标区能量除以整个采样平面能量；
- 联合成功：RMSE≤12%、覆盖率≥60%、旁区峰值≤−2 dB。

最后一项只是平台内部的归一化联合门限，不代表现实效应等级。

## 6. 快速配置结果

关键工况：阵元相位误差标准差8°、增益误差标准差5%、控制平面配准抖动标准差0.14λ、Rapp饱和尺度1.0。60次配对Monte Carlo得到：

| 方法 | 目标RMSE | 覆盖率 | 旁区峰值 | 联合成功率 |
|---|---:|---:|---:|---:|
| Point-Focus | 12.68% | 59.3% | −1.28 dB | 0.0% |
| Region-LS | 11.94% | 53.3% | −2.30 dB | 20.0% |
| Nominal-PGMS | 14.22% | 45.8% | −3.20 dB | 0.0% |
| **SR-PGMS-DPD** | **9.73%** | **71.2%** | **−2.41 dB** | **75.0%** |

所提方法相对Point-Focus、Region-LS和Nominal-PGMS的平均RMSE分别降低2.94、2.21和4.48个百分点；三组配对单侧Wilcoxon检验均达到显著水平。与此同时，Point-Focus的采样平面能量效率仍更高，Nominal-PGMS在部分旁区统计量上更低，说明问题存在真实的多目标折中，而不是单一方法在所有指标上统治。

## 7. 文件入口

```text
src/hpm_platform/field_control/region_shaping.py
src/hpm_platform/physics/power_amplifier.py
src/hpm_platform/evaluation/field_metrics.py
src/hpm_platform/workflows/field_control_v06.py
src/hpm_platform/visualization/field_control_v06.py
configs/field_control_v06.yaml
configs/field_control_v06_paper.yaml
```

运行：

```bash
python run_field_control_v06.py
```

打开：

```text
outputs_v06_field_control/field_control_v06_report_standalone.html
```

论文级配置已经准备，但未在仓库中预先宣称其统计结果。定稿前应固定超参数，运行高密度复算，并报告所有失败样本和置信区间。
