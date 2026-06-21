# Studio UI/UX 规范

前端技术栈：

- React
- TypeScript
- Vite
- Ant Design 5 中文 locale
- Ant Design Pro 应用壳
- FlexLayout React
- Three.js
- react-three-fiber
- @react-three/drei
- Zustand
- TanStack Query
- ECharts
- Tabler Icons
- Playwright

## 默认布局

顶部：文件、编辑、视图、场景、任务、求解、工具、帮助、撤销、重做、运行、停止。

左侧上部：场景对象树。

左侧下部：对象与资产库。

中央：三维场景视口，占据屏幕面积至少 60%。

右侧：当前选中对象属性面板。

底部可折叠：时间轴、求解任务、结果图表、日志。

## 默认隐藏

平台成熟度评分、A/B/C 等级、审计表、论文准备度、DOI 缺失提示、统计显著性审计和证据链台账不得出现在默认工作区。

## 视口原则

视口永久信息保持克制：选中轮廓、简洁图标、轨迹、场图和必要名称。完整数值只在悬停提示、属性面板和结果检查器中显示。
