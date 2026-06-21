# V2.0C 任务级仿真框架

## 定位

V2.0C 把平台从单次三维场景求解推进到 Mission First 任务级仿真。默认入口仍是 Scene First 的“场景编辑”，但场景页现在直接提供任务模板、时间线运行、结果归档和论文产物。

任务级仿真回答的问题是：

```text
当前场景在一个动态任务中表现如何？
```

而不是只回答：

```text
当前单次求解的验证指标是多少？
```

## 当前闭环

已实现的最小闭环：

```text
读取 CAEProject 场景
↓
选择任务模板
↓
生成目标运动时间线
↓
逐帧运行归一化控场求解
↓
统计目标覆盖、跟踪误差、保护区代理风险
↓
输出 HTML/CSV/JSON/ZIP 任务档案
```

## 内置模板

| 模板 | 名称 | 控制器 | 默认帧数 |
|---|---|---|---:|
| `MST-TRACK-001` | 目标运动控场任务 | `Predictive-PGMS` | 6 |
| `MST-DELAY-001` | 观测延迟对比任务 | `Delayed-PGMS` | 6 |
| `MST-STATIC-001` | 静态赋形基线任务 | `Static-PGMS` | 5 |

## API

```text
GET  /api/mission/templates
GET  /api/mission/status
POST /api/mission/run
GET  /api/mission/results/{mission_id}
```

`POST /api/mission/run` 支持：

```json
{
  "template_id": "MST-TRACK-001",
  "frames": 6,
  "controller": null,
  "label": "目标运动任务"
}
```

## 产物

任务结果写入：

```text
outputs_v20a_vv/mission_v20c/
```

每次运行包含：

- `mission_result.json`
- `timeline_metrics.csv`
- `summary.json`
- `timeline_fields.npz`
- `01_timeline_animation.html`
- `02_timeline_metrics.html`
- `03_trajectory.html`
- `HPM_CAE_timeline_report.html`
- 任务 ZIP 包

目录级索引：

- `outputs_v20a_vv/mission_v20c/index.json`
- `outputs_v20a_vv/mission_v20c/index.csv`

## 安全边界

任务结果仅用于波长尺度归一化任务研究。平台不输出：

- 真实毁伤概率；
- 真实作用距离；
- 现实作用距离；
- 器件阈值；
- 武器效能参数。

绝对功率仍只作为标定元数据，不用于反推真实作用距离或器件阈值。

## 后续路线

下一步 V2.0C 应继续补齐：

- 任务模板编辑器；
- 多目标和多保护区任务；
- 感知/测向结果接入任务状态；
- 阵列退化、遮挡和反射环境任务；
- 任务级对比和结果回放；
- 将任务产物接入 Paper Factory 的图表清单与补充材料。
