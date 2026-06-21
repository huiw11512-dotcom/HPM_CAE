# 面向高功率微波相控阵数字孪生平台的可信度验证与不确定度量化方法

## Abstract

本文面向归一化相控阵算法与降阶传播数字孪生平台，提出一套可复现的 Verification & Validation 体系。体系覆盖解析解验证、信号处理与波束形成基准、传播后端一致性、不确定度量化、敏感性分析和综合可信度评分。

## North Star Context

持续演进 HPM-DT（High-Power Microwave Digital Twin），构建一个面向高功率微波相控阵、效应分析与数字孪生研究的全中文任务级科研 CAE 平台。所有版本开发都必须服务于这个长期目标，而不是孤立地增加功能。

本文中的 V2.0A 只对应 HPM-DT 八层架构中的可信度层阶段成果，不替代平台长期目标。

## 1. Introduction

说明高功率微波相控阵数字孪生平台在算法研究、方案比较和报告生成中的价值，同时强调其与全波电磁仿真的边界差异。

## 2. Related Work

综述阵列因子解析验证、MUSIC/ESPRIT 测向、MVDR/LCMV 波束形成、模型 V&V、不确定度量化和敏感性分析方法。

## 3. HPM Phased-Array Digital Twin Architecture

介绍平台结构：阵列几何、归一化传播后端、感知模块、防护/控场模块、报告与 UI 层。强调不输出真实毁伤概率、作用距离和器件阈值。

## 4. Verification Against Analytical Solutions

描述 VV-01 至 VV-03。当前解析类用例通过数为 3 / 3。

## 5. Benchmark Validation of Signal Processing and Beamforming Modules

描述 MUSIC、ESPRIT、PAWR-MUSIC 与 MVDR/LCMV 约束响应验证。重点报告测向 RMSE、失败率、LCMV 约束残差和零陷深度。

## 6. Backend Consistency and Applicability Audit

说明混合后端、镜像后端、孔缝腔体后端在关闭附加机制后退化为自由空间后端的验证流程。

## 7. Uncertainty Quantification and Sensitivity Analysis

Monte Carlo 采用固定随机种子 20260620，峰值偏差均值为 0.01155，95%CI 宽度为 0.01637。OAT 敏感性排序中最敏感因素为 目标指向偏移。

## 8. Credibility Scoring Framework

提出 0-100 分可信度评分：解析验证、基准复现、不确定度覆盖和后端适用性四项加权。当前平台评分为 91.58，等级为 A。

## 9. Discussion

讨论该体系的可审计性、可复现性、论文图表输出能力，以及仍需补充的复杂场景。

## 10. Conclusion

总结 V2.0A 可信度验证体系能够把平台从“可运行”推进到“可验证、可复现、可写论文”的状态。
