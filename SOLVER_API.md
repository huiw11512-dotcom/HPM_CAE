# Studio Solver API

统一求解器协议：

```text
SolverBackend
- id: str
- name: str
- validate(scene, mission) -> ValidationResult
- prepare(scene, mission) -> PreparedProblem
- run(problem, progress, cancel) -> ResultDataset
- result_schema() -> ResultSchema
```

## Studio 0.1 求解范围

- 多阵列；
- 多发射实体；
- 多接收实体；
- 任意数量运动实体；
- 自由空间标量传播；
- 阵列方向响应；
- Point/Line/Plane Probe；
- 动态时间帧；
- 可取消任务；
- 进度流式返回。

不得假设只有一个目标。

结果内存模型优先采用 xarray Dataset；大规模时空数据保存为 Zarr 或 HDF5；指标表保存为 Parquet 或 CSV；结果 manifest 保存为 JSON。
