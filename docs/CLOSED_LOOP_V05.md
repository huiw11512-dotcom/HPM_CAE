# V0.5 动态感知—防护闭环技术说明

## 1. 研究问题

V0.4将一个静态DOA置信域转换为宽零陷，但没有回答三个动态问题：

1. 感知结果经过若干帧处理和传输后，如何补偿方向陈旧；
2. 多个干扰源同时运动时，如何分配有限的零陷子空间自由度；
3. 局部接收通道失效时，如何避免鲁棒波束形成继续依赖异常通道。

V0.5把V0.3的健康加权PAWR前端、二维DOA不确定性、时间戳Kalman跟踪和V0.4角域特征零陷连接成一个真正的动态接收防护闭环。

> 本模块仅处理相对白噪声方差归一化的接收信号。它不包含真实高功率源预算、传播射程、设备阈值或毁伤推断。

## 2. 数据与状态接口

每个感知包包含：

```text
MeasurementPacket
├── acquisition_frame            采集时间戳
├── ready_frame                  权值侧可用时间戳
├── estimates_deg[K,2]           K个DOA估计
├── covariance_deg2[K,2,2]       局部角度协方差
├── sample_covariance[M,M]       采集时刻阵列协方差
├── sensor_reliability[M]        通道健康度
└── fault_mask[M]                仅仿真评估使用的故障真值
```

保护模块不会读取未来真实方向或故障真值；真值只用于最终评价。

## 3. 从PAWR谱到二维DOA协方差

在PAWR连续估计点附近建立局部角网格，使用信号子空间补投影计算MUSIC谱：

\[
P(\theta,\phi)=\frac{1}{\|a\|^2-\|E_s^H a\|^2}.
\]

将温度缩放后的局部对数谱归一化为离散后验：

\[
p_g \propto \exp\left(\frac{\log P_g-\max \log P}{T}\right),
\]

再计算二维均值与协方差：

\[
\Sigma_z=\sum_g p_g(\xi_g-\bar\xi)(\xi_g-\bar\xi)^T+\Sigma_{\rm grid}.
\]

为防止有限网格产生虚假“零方差”，代码设置了量化项和标准差下限。健康度尾部均值会进一步放大测量协方差，使局部坏通道显式进入后端置信域。

## 4. 时间戳感知协方差传播

每条轨迹采用状态

\[
x=[\theta,\phi,\dot\theta,\dot\phi]^T
\]

的常速度Kalman模型。感知包在采集时间 \(t_m\) 形成、在 \(t_m+L\) 到达。跟踪器先在原始采集时间吸收测量，再将状态和协方差传播到当前防护帧 \(t\)：

\[
\hat x_{t|m}=F(t-t_m)\hat x_{m|m},
\]

\[
P_{t|m}=F P_{m|m}F^T+Q(t-t_m).
\]

因此延迟越大，角度协方差自然增大，而不是手工把固定“±7°”继续沿用。

## 5. 多干扰PCP-HybridNull

每个预测轨迹的二维协方差生成旋转高斯置信椭圆。其概率加权角流形为

\[
A_k=[\sqrt{p_1}a(\xi_1),\ldots,\sqrt{p_G}a(\xi_G)].
\]

对 \(A_k\) 做SVD并按能量覆盖选择模式。多个干扰源的模式以轮转方式拼接并正交化，避免一个宽扇区耗尽全部秩。保护协方差为

\[
R_{\rm eff}=R+\lambda_s\frac{\operatorname{tr}(R)}{M}
\frac{1}{K}\sum_k R_{{\rm sector},k}+R_{\rm health}.
\]

其中健康惩罚项提高低可靠通道的对角代价。最终求解带目标无失真约束和多扇区特征零陷约束的LCMV，并在白噪声增益或约束条件数不满足时逐级回退秩；若硬约束仍不稳定，则退化到软扇区MVDR，而不是返回数值爆炸权值。

## 6. 仿真协议

快速配置采用：

- 8×8半波长面阵；
- 两个独立移动干扰源，INR分别为28 dB和24 dB；
- 目标SNR为-5 dB；
- 96快拍/帧；
- 感知每4帧更新，处理滞后2帧；
- 两阶段引入4个局部异常通道；
- 代表序列40帧；
- Monte Carlo每点10次、每次28帧；
- 消融12次。

主基线：Static-Point、Delayed-Point、Predictive-Point、Delayed-FixedCR，以及PCP-HybridNull。

## 7. 快速配置结果

代表性序列：

| 方法 | 平均输出SINR | 可用率 | 平均最坏干扰响应 |
|---|---:|---:|---:|
| Static-Point | -10.94 dB | 7.5% | -22.02 dB |
| Delayed-Point | -0.02 dB | 17.5% | -33.20 dB |
| Predictive-Point | 4.49 dB | 45.0% | -38.11 dB |
| Delayed-FixedCR | 8.18 dB | 82.5% | -44.45 dB |
| PCP-HybridNull | 9.07 dB | 87.5% | -47.04 dB |

4帧处理滞后、10次配对Monte Carlo下，PCP-HybridNull相对Delayed-FixedCR平均提升1.03 dB，单侧Wilcoxon检验 \(p=0.0137\)。相对Delayed-Point和Predictive-Point分别提升8.84 dB和5.63 dB。

代表序列PAWR更新点平均测向误差为0.275°，中位感知与协方差提取耗时33.62 ms；保护权值中位更新时间约0.71 ms。故障召回率在当前强异常配置中为100%，但不能外推到弱故障或真实硬件。

## 8. 消融解释

快速消融的平均序列SINR：

- 仅预测点零陷：4.94 dB；
- 预测＋固定扇区：8.74 dB；
- 仅DOA协方差、无预测：6.28 dB；
- PCP去掉健康惩罚：8.80 dB；
- 完整PCP-HybridNull：9.75 dB。

这说明“预测”和“角域覆盖”是主要收益来源，健康惩罚在当前4通道故障条件下提供约0.95 dB增益。该结论仍需论文配置的更大样本复算。

## 9. 失效边界

- 当速度或更新间隔继续增大，置信域触及最大半宽后不再覆盖真实方向；
- 多个干扰方向过近时，轨迹关联和角流形子空间可能合并；
- 低可靠通道的健康度仅来自功率局部一致性，不能替代硬件校准；
- 当前Kalman模型采用局部 \((\theta,\phi)\) 坐标，不适合跨越方位角包络边界的长轨迹；
- 全部结论只对应归一化窄带接收模型。

## 10. 复现

```bash
python run_closed_loop_v05.py
```

论文级配置：

```bash
python run_closed_loop_v05.py \
  --config configs/closed_loop_v05_paper.yaml \
  --output outputs_v05_paper
```

快速报告：`outputs_v05_closed_loop/closed_loop_v05_report_standalone.html`。
