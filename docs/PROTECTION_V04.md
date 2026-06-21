# V0.4：DOA不确定条件下的接收端鲁棒宽零陷防护

## 1. 研究问题

V0.3输出的是干扰方向估计及其不确定区间。若接收权值只在单一估计方向形成点零陷，权值更新滞后、目标运动或估计偏差都会使实际干扰离开零点，导致抑制性能快速下降。

V0.4研究一个纯归一化、纯接收端的问题：

> 如何把感知模块的方向置信区间显式映射为接收阵列的角域约束，在保持主瓣响应和白噪声增益的同时，提高零陷对方向漂移的稳定性？

公开实现只处理阵列接收、协方差、相对功率和输出SINR，不包含绝对源功率、链路预算、设备易损阈值或毁伤推断。

## 2. 信号与时变方向模型

训练阶段的归一化窄带观测为

\[
\mathbf{x}[n] = \mathbf{G}\mathbf{a}(\Omega_s)s[n]
+ \mathbf{G}\mathbf{a}(\widehat{\Omega}_i)i[n]
+ \mathbf{v}[n],
\]

其中 \(\mathbf{G}\) 表示未知通道幅相误差，\(\widehat{\Omega}_i\) 为感知模块给出的干扰方向中心。权值更新后，评估阶段的干扰方向变为

\[
\Omega_i = \widehat{\Omega}_i + \Delta\Omega,
\]

从而模拟测向误差、更新延迟或方向运动。训练协方差与评估方向严格分离，避免用“未来真实方向”参与权值设计。

## 3. 置信域角流形

感知不确定性被表示为二维椭圆：

\[
\left(\frac{\theta-\widehat\theta_i}{h_\theta}\right)^2
+\left(\frac{\phi-\widehat\phi_i}{h_\phi}\right)^2\leq 1.
\]

在椭圆内采样方向并使用高斯权重 \(p_g\)，构造加权流形矩阵

\[
\mathbf{B}=
\left[
\sqrt{p_1}\mathbf{a}(\Omega_1),\ldots,
\sqrt{p_G}\mathbf{a}(\Omega_G)
\right].
\]

奇异值分解为

\[
\mathbf{B}=\mathbf{U}\mathbf{\Sigma}\mathbf{V}^{H}.
\]

选取最小秩 \(r\)，使累计能量达到配置阈值 \(\rho\)：

\[
\frac{\sum_{k=1}^{r}\sigma_k^2}
{\sum_k\sigma_k^2}\geq\rho.
\]

这比在几十个角度上逐点施加硬约束更节省阵列自由度，也比单点零陷更能覆盖方向不确定性。

## 4. CR-HybridNull权值

置信域协方差定义为

\[
\mathbf{S}_{\mathcal U}
=\sum_g p_g\mathbf{a}(\Omega_g)\mathbf{a}^{H}(\Omega_g),
\]

并归一化为 \(\operatorname{tr}(\mathbf{S}_{\mathcal U})=M\)。有效协方差为

\[
\mathbf{R}_{\mathrm{eff}}
=\widehat{\mathbf{R}}_x
+\beta\frac{\operatorname{tr}(\widehat{\mathbf{R}}_x)}{M}
\mathbf{S}_{\mathcal U}.
\]

前 \(r\) 个角域特征向量形成硬零陷子空间：

\[
\mathbf{C}=[\mathbf{a}_s,\mathbf{U}_r],\qquad
\mathbf{f}=[1,0,\ldots,0]^T.
\]

最终权值采用对角加载LCMV闭式解：

\[
\mathbf{w}=
\mathbf{R}_{\delta}^{-1}\mathbf{C}
\left(\mathbf{C}^{H}\mathbf{R}_{\delta}^{-1}\mathbf{C}\right)^{-1}
\mathbf{f}.
\]

若候选秩造成白噪声增益低于下限，或约束Gram矩阵条件数超过阈值，代码会逐级降低秩，而不是返回高范数不稳定解。

## 5. 实现方法与基线

主工作流比较：

- Conventional：常规接收波束；
- DL-MVDR：对角加载MVDR；
- Point-LCMV：在估计中心施加单点零约束；
- Derivative-LCMV：同时约束中心响应和一阶角导数；
- Sector-MVDR：将置信域协方差作为软惩罚；
- CR-HybridNull：角域特征子空间硬零陷与残余软惩罚联合设计。

消融实验额外包含密集采样扇区LCMV，用于观察“更强硬约束”与白噪声增益损失之间的代价。

## 6. 统一评价指标

- 独立评估阶段的输出SINR；
- 实际漂移方向的相对阵列响应；
- 置信域内最坏相对响应；
- 白噪声增益WNG；
- 目标方向增益偏差；
- 输出SINR达到5 dB的防护成功率；
- 权值更新时间和自适应子空间秩。

所有Monte Carlo方法在同一试验内共享噪声、通道误差和漂移方向，支持配对统计检验。

## 7. 快速配置结果

8×8阵列、目标SNR为-5 dB、干扰INR为30 dB、128快拍、通道相位误差标准差2°。每个标准点30次配对试验。

在6°方向漂移下：

| 方法 | 平均输出SINR | 实际方向响应 | 成功率 | 平均WNG |
|---|---:|---:|---:|---:|
| DL-MVDR | -8.13 dB | -26.93 dB | 0.0% | 17.98 dB附近 |
| Point-LCMV | -8.10 dB | -26.96 dB | 0.0% | 17.95 dB |
| Derivative-LCMV | 1.66 dB | -37.40 dB | 23.3% | 17.85 dB附近 |
| Sector-MVDR | 7.31 dB | -45.03 dB | 70.0% | 17.86 dB附近 |
| CR-HybridNull | 8.83 dB | -46.99 dB | 90.0% | 17.69 dB |

CR-HybridNull相对Point-LCMV平均提升16.93 dB，配对单侧Wilcoxon检验 \(p=9.31\times10^{-10}\)；相对Derivative-LCMV提升7.17 dB，\(p=3.07\times10^{-8}\)。相对Sector-MVDR平均提升1.52 dB，但快速配置的单侧检验 \(p\approx0.0502\)，不应据此宣称统计上全面优越。

方向漂移达到10°、明显超出默认7°置信半宽后，Sector-MVDR和CR-HybridNull均下降到约2 dB，明确给出了方法的覆盖边界。置信半宽扫参显示快速配置在10°附近达到最佳均值，随后因约束秩增加和自由度消耗而下降。

## 8. 复现入口

```bash
python -m pip install -r requirements.txt
python run_protection_v04.py
```

结果目录：

```text
outputs_v04_protection/
├── protection_v04_report_standalone.html
├── results_summary.json
├── monte_carlo_trials.csv
├── monte_carlo_summary.csv
├── representative_case.npz
├── paper_table_key_results.csv
└── 00...16 自动图
```

论文级配置：

```bash
python run_protection_v04.py \
  --config configs/protection_v04_paper.yaml \
  --output outputs_v04_paper
```

## 9. 当前边界与下一步

当前模型仍是单强干扰、窄带、远场、独立通道幅相误差和白噪声。下一步应将V0.3逐试验输出的方向协方差直接转换为V0.4椭圆参数，并加入多干扰源、在线更新滞后、阵元失效及跟踪滤波，形成真正的“感知—防护”闭环，而不是手工传入置信半宽。
