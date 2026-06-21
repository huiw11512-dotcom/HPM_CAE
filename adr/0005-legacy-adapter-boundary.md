# ADR 0005: Legacy Adapter Boundary

状态：Accepted

## 决策

旧算法可以通过 adapter 接入新 SolverBackend。旧 UI、旧 project_model、旧 workbench3d 和旧 app_vXX 不得成为新 domain 依赖。

## 后果

可复用算法被保留，产品主干不再被旧区域赋形实验模型锁死。迁移器负责旧工程到 Studio 工程的显式转换和报告。
