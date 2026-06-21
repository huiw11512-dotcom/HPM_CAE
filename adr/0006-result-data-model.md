# ADR 0006: Result Data Model

状态：Accepted

## 决策

结果数据分为：

- ResultDataset 内存模型；
- 大规模时空数据：Zarr 或 HDF5；
- 指标表：Parquet 或 CSV；
- 结果 manifest：JSON；
- 前端按需加载切片、曲线和对象关联结果。

## 后果

浏览器不一次性接收完整体数据。结果页面以三维场景动画、切片、轨迹、传播路径和对象曲线为主，详细指标进入结果检查器。
