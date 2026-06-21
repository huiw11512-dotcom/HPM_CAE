# 论文线2工作骨架：DOA不确定条件下的接收端鲁棒宽零陷

## 暂定题目

中文：**面向方向漂移防护的置信域特征子空间宽零陷波束形成方法**

英文：**Confidence-Region Eigenspace Wide-Null Beamforming for Receive Protection under Interferer Direction Drift**

## 核心科学问题

单点零陷方法默认干扰方向在权值更新周期内保持不变。实际系统中，测向误差、目标运动和处理延迟会使真实方向偏离零点。论文回答：如何将感知置信区间转化为低维角域约束，并在零陷覆盖、白噪声增益和阵列自由度之间取得可解释折中？

## 建议贡献表述

1. 建立“训练方向—评估方向”分离的方向漂移验证协议，避免使用未来真实方向设计权值；
2. 将二维DOA置信椭圆映射为概率加权阵列流形，并通过SVD提取紧凑角域特征子空间；
3. 提出硬特征子空间零陷与软置信域协方差惩罚联合的CR-HybridNull闭式权值；
4. 引入WNG与条件数门限的自适应秩回退，量化置信域过窄和过宽的失效边界；
5. 通过配对Monte Carlo比较点LCMV、导数LCMV、扇区MVDR和密集扇区约束，并同时报告SINR、最坏响应、WNG、成功率和时延。

不要把“使用SVD”本身写成创新；创新应落在感知不确定性到角域约束的接口、硬软联合设计以及可验证的漂移协议上。

## 论文结构

### 1. Introduction

- 点零陷对DOA误差和更新延迟敏感；
- 密集扇区硬约束消耗自由度并降低WNG；
- 现有感知与波束形成往往各自优化，缺少置信信息接口；
- 给出本文贡献和公开数值验证边界。

### 2. Signal and Drift Model

- 8×8 URA及坐标约定；
- 训练期归一化接收模型；
- 评估期随机方向漂移；
- 通道幅相失配；
- 独立训练与评估指标。

### 3. Proposed CR-HybridNull

- 置信椭圆与概率加权流形；
- 角域SVD与能量秩；
- 置信域协方差软惩罚；
- 特征子空间硬约束；
- WNG/条件数自适应秩回退；
- 复杂度分析。

### 4. Baselines and Protocol

- Conventional、DL-MVDR、Point-LCMV；
- 一阶导数LCMV；
- Sector-MVDR；
- 密集扇区LCMV消融；
- 所有方法使用相同训练样本和随机扰动；
- 每点论文配置300次，消融500次。

### 5. Results

推荐主图映射：

1. Fig. 1：`00_cr_hybridnull_mechanism.svg`；
2. Fig. 2：`01_point_lcmv_map.png`；
3. Fig. 3：`02_cr_hybridnull_map.png`；
4. Fig. 4：`03_drift_cut.png`；
5. Fig. 5：`06_sinr_vs_drift.png`；
6. Fig. 6：`07_protection_rate_vs_drift.png`；
7. Fig. 7：`10_sinr_vs_phase_error.png`；
8. Fig. 8：`11_sinr_vs_uncertainty_width.png`；
9. Fig. 9：`15_ablation.png`；
10. Fig. 10：`16_runtime.png`。

关键表：`paper_table_key_results.tex`。

### 6. Discussion

- 默认7°置信域内的性能区间；
- 10°漂移后的覆盖边界；
- 与Sector-MVDR的差异在快速配置下处于统计临界，需论文级复算；
- 密集硬约束可能提高成功率但牺牲WNG，不能只看单一SINR均值；
- 单干扰、窄带和理想阵元方向图的限制。

### 7. Conclusion

只总结接收防护与归一化阵列结果，不外推到真实设备抗毁等级。

## 当前可支持的审慎结论

- 在默认6°漂移工况，CR-HybridNull显著优于点LCMV和一阶导数LCMV；
- 与软扇区MVDR相比均值更高、实际方向响应更低，但快速试验的统计显著性处于边界；
- 置信域扩大到约10°后收益达到峰值，继续扩大将消耗更多角域自由度；
- 超出设计置信域后性能下降，方法不是无条件鲁棒。

## 定稿前必须补充

- 运行`protection_v04_paper.yaml`；
- 至少加入两组不同目标/干扰角度；
- 加入多干扰源和阵元失效；
- 用开发集确定能量阈值、软惩罚系数和WNG下限；
- 报告超参数敏感性和计算复杂度；
- 将V0.3估计协方差真实接入，而不是固定置信半宽。
