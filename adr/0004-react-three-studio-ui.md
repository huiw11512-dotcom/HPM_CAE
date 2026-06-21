# ADR 0004: React Three Studio UI

状态：Accepted

## 决策

Studio 前端采用 React、TypeScript、Vite、Ant Design 5、Ant Design Pro、FlexLayout React、Three.js、react-three-fiber、drei、Zustand、TanStack Query、ECharts 和 Tabler Icons。

## 原因

该组合能提供桌面式 CAE 工作区、稳定组件库、三维视口和前后端状态管理。禁止继续使用 Bootstrap Dashboard 管理后台风格作为主工作台。

## 后果

前端不包含物理求解公式，所有求解经 API 或 WebSocket 调用后端。
