# V0.3 鲁棒相干多径感知：PAWR-MUSIC

## 1. 研究问题

V0.2 证明了前后向空间平滑（FBSS）可以恢复完全相干路径造成的协方差秩亏。V0.3进一步考虑三类更接近数值试验实际的非理想因素：

1. 少量接收通道出现局部增益/相位异常和附加噪声；
2. 快拍有限、SNR较低，MUSIC谱出现伪峰或峰位抖动；
3. 环境模型只能给出宽松的直达/反射角域先验，而不是精确DOA。

公开版只使用相对噪声归一化的窄带阵列观测，不包含绝对源功率、设备易损阈值或毁伤推断。

## 2. PAWR组成

PAWR是 **Prior-Assisted Adaptive Weighted Reconstruction** 的缩写。

### 2.1 通道健康度

对每个阵元计算快拍平均功率，并与局部中值功率面比较。突变残差经MAD尺度归一化后映射到 `[0,1]` 可靠度。该方法保留由相干干涉产生的平滑空间起伏，只惩罚孤立异常。

### 2.2 子阵自适应加权FBSS

每个重叠子阵的权重由其阵元可靠度几何均值产生，并保留一个均匀权重下限。加权子阵协方差经前后向共轭平均后形成鲁棒FBSS协方差。

### 2.3 轻量二维BTTB正则

URA平移不变性对应二维块Toeplitz-块内Toeplitz结构。完全投影会抑制仍然存在的相干交叉项，因此PAWR仅采用2%的轻量混合；完整BTTB投影被保留为独立强基线和消融项。

### 2.4 宽松路径先验与连续子空间拟合

配置只给出两个宽松中心 `(20°, -5°)`、`(33°, 9°)`，与真值分别存在约3°偏差。每个中心对应8°宽的球面高斯先验。算法先从MUSIC谱中选择对应扇区的粗峰，再连续最小化噪声子空间投影：

\[
J_k(\theta,\phi)=\frac{\mathbf a^H\mathbf P_n\mathbf a}{\mathbf a^H\mathbf a}
+\lambda\left(\frac{d_\Omega((\theta,\phi),\mu_k)}{\sigma_k}\right)^2.
\]

先验项权重很小，主要用于排除低SNR下的跨扇区伪峰。`prior_bias_sweep`专门检验该假设的失效边界。

### 2.5 低秩协方差重构

利用连续DOA构造阵列流形矩阵，并拟合源协方差与白噪声项：

\[
\widehat{\mathbf R}=\mathbf A\widehat{\mathbf S}\mathbf A^H+\widehat\sigma_n^2\mathbf I.
\]

该重构结果供后续感知-抑制接口使用，也用于生成无栅格量化误差影响的谱图。

## 3. 基准与消融

完整比较包含：

- FBSS-MUSIC；
- BTTB-FBSS-MUSIC；
- 二维FBSS-ESPRIT；
- PAWR-MUSIC。

消融包含：均匀FBSS、健康加权FBSS、健康加权加无先验离栅格拟合、完整PAWR。

## 4. 快速配置结果解读

每点20次试验仅用于平台验收。`-8 dB + 2个局部异常通道`时：

- FBSS-MUSIC平均RMSE约0.913°；
- FBSS-ESPRIT约0.781°；
- PAWR-MUSIC约0.782°；
- PAWR相对FBSS的配对单侧Wilcoxon检验 `p≈0.0133`；
- PAWR与ESPRIT无显著差异，不能声称全面优于ESPRIT。

完整BTTB投影在中高SNR下维持约1.7°偏差，说明“结构投影越强越好”并不成立。先验追加偏差达到10°时，PAWR分辨率显著崩溃；这是需要在论文中主动报告的适用边界。

## 5. 复现实验

快速验收：

```bash
python run_perception_v03.py
```

论文级配置：

```bash
python run_perception_v03.py \
  --config configs/perception_v03_paper.yaml \
  --output outputs_v03_paper
```

论文级配置使用0.5°扫描栅格和每点200次试验，运行时间明显更长。

## 6. 下一步

V0.4将把DOA估计及其不确定区间传递给接收端鲁棒宽零陷算法。评价重点是方向误差区间内的最坏情况抑制、主瓣损失、阵元失效和算法时延，而不是绝对高功率效应。
