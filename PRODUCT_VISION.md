# HPM-DT Studio 产品愿景

HPM-DT Studio 是面向高功率微波、相控阵和复杂电磁环境研究的系统级场景与任务仿真工作台。

英文副标题：

```text
System-Level Electromagnetic Scene and Mission Simulation Studio
```

Studio 的默认问题是：

```text
你想建立什么场景并运行什么任务？
```

而不是：

```text
你想查看哪项验证评分？
```

## 产品边界

Studio 不模仿 CST/HFSS 的全波求解，也不把归一化模型包装成真实毁伤或作用距离结论。它解决的是系统级电磁场景、阵列系统、动态对象、探针、任务和结果回放之间的建模与快速仿真问题。

## Studio 0.1 垂直切片

Studio 0.1-alpha 只交付一条完整闭环：

```text
通用物理场景
→ 通用多实体任务
→ 自由空间快速求解
→ 三维可视化
→ 保存和恢复
```

可信度验证、论文工厂、数据导入、插件管理和成熟度评分全部保留在 legacy 或高级工具中，不进入默认工作区。
