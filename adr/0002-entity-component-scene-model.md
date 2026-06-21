# ADR 0002: Entity Component Scene Model

状态：Accepted

## 决策

Studio 核心采用 Scene Graph + Entity Component System。核心只定义通用 Entity，能力由 Component 提供。

## 禁止

核心不定义 TargetRegion、ProtectedZone、ObservationPlane 作为物理实体，不通过固定编号或实体名称判断行为。

## 后果

多阵列、多接收器、多运动对象和复杂环境可以用统一实体组合表达。分析区域从物理场景中剥离，归入任务和探针层。
