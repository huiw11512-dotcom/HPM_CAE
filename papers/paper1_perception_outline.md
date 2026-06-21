# 论文一工作骨架：相干多径与模型失配下的二维测向

## 暂定题目

**中文**：阵列流形失配下基于先验加权协方差重构的相干多径二维测向方法  
**英文**：Prior-Weighted Covariance Reconstruction for Two-Dimensional DOA Estimation under Coherent Multipath and Array-Manifold Mismatch

> 当前 V0.2 已完成可信基线与统计框架；“先验加权协方差重构”尚待 V0.3 实现。经典 FBSS 不应单独包装成原创算法。

## 核心科学问题

在相干多径导致信号协方差秩塌缩、阵列幅相误差导致导向矢量失配时，如何利用有限传播/校准先验重构可用于子空间测向的稳健协方差，同时避免过度依赖精确信道模型？

## 可检验假设

1. 均匀 FBSS 能恢复相干路径秩，但所有子阵等权会放大局部失配；
2. 基于子阵一致性与校准置信度的自适应权重，可在中等模型失配下减小DOA误差；
3. 在先验偏差存在时，正则化/最坏情况约束能避免权重塌缩，并优于硬先验约束。

## 计划贡献

1. 建立矩形阵列相干多径与随机流形失配的统一归一化观测模型；
2. 提出先验加权的重叠子阵协方差重构方法；
3. 给出权重正则化、有效子阵数和复杂度分析；
4. 通过离栅格真值、非相干对照、模型失配和域外参数验证方法边界；
5. 提供可复现 Python 代码、逐试验数据和自动论文制图。

## 当前已完成的图表

| 论文图 | 当前文件 | 用途 |
|---|---|---|
| Fig. 1 | `00_fbss_mechanism.svg` | 相干秩塌缩与空间平滑机理 |
| Fig. 2(a) | `01_standard_music_spectrum.png` | 传统MUSIC伪峰 |
| Fig. 2(b) | `02_fbss_music_spectrum.png` | FBSS双峰恢复 |
| Fig. 2(c) | `10_incoherent_control_music_spectrum.png` | 非相干消融对照 |
| Fig. 3 | `03_eigenvalue_rank_restoration.png` | 第二信号特征值恢复 |
| Fig. 4 | `04_rmse_vs_snr.png` | RMSE-SNR |
| Fig. 5 | `05_resolution_vs_snr.png` | 分辨成功率-SNR |
| Fig. 6 | `06_rmse_vs_snapshots.png` | 有限快拍敏感性 |
| Fig. 7 | `07_rmse_vs_phase_error.png` | 流形失配敏感性 |
| Fig. 8 | `09_error_cdf_snr0.png` | 误差分布 |

这些图目前展示 `Standard MUSIC` 与 `FBSS-MUSIC`，V0.3需加入提出方法及更多基准。

## 必须补齐的实验

- 提出方法：先验加权/鲁棒加权空间平滑；
- 基准：均匀FBSS、Toeplitz协方差重构、空间差分、二维ESPRIT或适配的张量方法；
- 路径夹角扫描：验证分辨极限；
- 相干系数扫描：从独立到完全相干；
- 子阵尺寸扫描：孔径与子阵数量折中；
- 路径数误设：`K-1`、`K`、`K+1`；
- 增益误差、相位误差、阵元失效和互耦代理模型；
- 先验偏差与先验缺失消融；
- 运行时间、内存和复杂度；
- 论文配置每点至少300次试验，报告置信区间与配对统计检验。

## 论文结构

1. Introduction：问题、缺口、贡献；
2. Signal and uncertainty model；
3. Baseline rank-collapse analysis；
4. Proposed prior-weighted covariance reconstruction；
5. Complexity and robustness discussion；
6. Numerical experiments；
7. Limitations and conclusion。

## 当前允许写入摘要的结论

- 平台可稳定复现相干多径导致的二维MUSIC失效；
- 空间平滑可以恢复第二信号特征值并显著改善基线测向；
- 低SNR和强阵列流形失配仍构成清晰性能边界；
- 非相干对照排除了孔径不足和实现错误。

## 当前不能写的结论

- “提出了新的FBSS算法”；
- “适用于真实HPM系统”或“达到工程部署要求”；
- “毁伤/反制有效”；
- 未经300次以上正式配置复算的精确百分比；
- 未与足够强基准比较前声称“优于现有方法”。
