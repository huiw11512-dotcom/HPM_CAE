from __future__ import annotations

import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
OUT = ROOT / "docs" / "HPM-DT_Studio_0.1_验收报告.html"


def data_uri(path: Path) -> str:
    mime = "image/svg+xml" if path.suffix.lower() == ".svg" else "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")

initial = data_uri(ASSETS / "00_场景工作台初始界面.png")
solved = data_uri(ASSETS / "01_城市多对象动态场景求解结果.png")
chart = data_uri(ASSETS / "02_接收曲线与三维结果.png")
architecture = data_uri(ASSETS / "04_场景优先系统架构图.png")

html = f"""<!doctype html>
<html lang='zh-CN'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>HPM-DT Studio 0.1 Alpha 验收报告</title>
<style>
:root{{--ink:#172033;--muted:#66758a;--line:#dce4ee;--blue:#2563eb;--green:#059669;--bg:#f5f7fb}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);font-family:"Microsoft YaHei UI","PingFang SC",sans-serif;color:var(--ink);line-height:1.65}}
.hero{{padding:56px 7vw 42px;background:linear-gradient(135deg,#0d1726,#172c4b);color:#fff}}
.hero h1{{margin:0 0 8px;font-size:38px}}.hero p{{margin:0;color:#b9c8dd;font-size:17px}}
.wrap{{max-width:1280px;margin:0 auto;padding:36px 28px 70px}}
.card{{background:#fff;border:1px solid var(--line);border-radius:16px;padding:26px;margin:0 0 24px;box-shadow:0 8px 24px rgba(20,38,63,.05)}}
h2{{font-size:24px;margin:0 0 18px}}h3{{font-size:17px;margin:20px 0 8px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}
.metric{{padding:18px;border:1px solid var(--line);border-radius:12px;background:#fbfcfe}}
.metric small{{display:block;color:var(--muted);margin-bottom:7px}}.metric strong{{font-size:25px;color:#0f2c56}}
img{{display:block;width:100%;border-radius:12px;border:1px solid #dce4ee;background:#fff}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:12px 14px;border-bottom:1px solid var(--line);text-align:left}}th{{background:#f6f8fb}}
.ok{{color:var(--green);font-weight:700}}.tag{{display:inline-block;padding:3px 9px;border-radius:999px;background:#dbeafe;color:#1d4ed8;font-size:12px;margin-right:5px}}
.note{{padding:16px;border-left:4px solid #f59e0b;background:#fff7ed;color:#7c4310;border-radius:8px}}
code{{background:#eef2f7;padding:2px 6px;border-radius:5px}}ul{{padding-left:22px}}
@media(max-width:900px){{.grid,.two{{grid-template-columns:1fr}}.hero h1{{font-size:30px}}}}
</style>
</head>
<body>
<section class='hero'>
  <h1>HPM-DT Studio 0.1 Alpha</h1>
  <p>场景优先的系统级电磁任务仿真工作台｜重启版验收报告</p>
</section>
<main class='wrap'>
<section class='card'>
<h2>一、这次真正重做了什么</h2>
<p>本版本不是给旧验证后台换皮，而是替换了产品的核心领域模型。场景由通用物理实体和组件组成；任务通过角色和组件查询选择任意数量对象；空间区域只作为探针或分析对象存在。</p>
<div><span class='tag'>物理对象优先</span><span class='tag'>任意实体数量</span><span class='tag'>任务查询</span><span class='tag'>视觉结果优先</span><span class='tag'>.hpmdt工程</span></div>
</section>
<section class='card'>
<h2>二、动态示例快速验收</h2>
<div class='grid'>
<div class='metric'><small>阵列发射实体</small><strong>2</strong></div>
<div class='metric'><small>接收实体</small><strong>4</strong></div>
<div class='metric'><small>独立运动实体</small><strong>3</strong></div>
<div class='metric'><small>动态时间帧</small><strong>30</strong></div>
<div class='metric'><small>平均归一化接收幅度</small><strong>0.260</strong></div>
<div class='metric'><small>最低归一化接收幅度</small><strong>0.028</strong></div>
<div class='metric'><small>时间稳定性代理</small><strong>94.4%</strong></div>
<div class='metric'><small>自动测试</small><strong>18/18</strong></div>
</div>
<p class='note'>以上为归一化系统级代理结果，只用于验证场景—任务—求解—结果闭环，不对应真实功率、作用距离、器件阈值或现实效应概率。</p>
</section>
<section class='card'>
<h2>三、工作台实机界面</h2>
<img src='{solved}' alt='城市多对象动态场景求解结果'>
<p>中央三维视口是主角：两个阵列、三个运动对象、建筑环境、接收设备、轨迹和动态场切片共同进入一个任务。默认界面不显示平台成熟度、论文准备度或大段审计表。</p>
</section>
<section class='card two'>
<div><h2>场景编辑状态</h2><img src='{initial}' alt='场景工作台初始界面'></div>
<div><h2>接收曲线与结果</h2><img src='{chart}' alt='接收曲线与三维结果'></div>
</section>
<section class='card'>
<h2>四、新系统架构</h2>
<img src='{architecture}' alt='场景优先系统架构图'>
</section>
<section class='card'>
<h2>五、功能验收表</h2>
<table>
<thead><tr><th>能力</th><th>验收状态</th><th>说明</th></tr></thead>
<tbody>
<tr><td>通用 Entity + Components</td><td class='ok'>通过</td><td>对象能力来自组件，不来自“目标1”等固定类型。</td></tr>
<tr><td>任意数量任务参与对象</td><td class='ok'>通过</td><td>任务使用 <code>role:</code> 与 <code>component:</code> 查询。</td></tr>
<tr><td>多阵列、多接收器</td><td class='ok'>通过</td><td>动态示例为2个阵列、4个接收实体。</td></tr>
<tr><td>动态运动与时间线</td><td class='ok'>通过</td><td>3个独立路径对象、30帧求解与回放。</td></tr>
<tr><td>场切片和对象曲线</td><td class='ok'>通过</td><td>平面探针与逐接收对象时间曲线。</td></tr>
<tr><td>.hpmdt工程保存/恢复</td><td class='ok'>通过</td><td>ZIP容器保存场景、任务、结果索引及结果数据。</td></tr>
<tr><td>全中文本地工作台</td><td class='ok'>通过</td><td>FastAPI + 本地开源前端资源，不依赖公共CDN。</td></tr>
<tr><td>真正的Three.js变换Gizmo</td><td>下一阶段</td><td>0.1使用Plotly WebGL完成可运行垂直闭环，0.2替换为Three.js编辑视口。</td></tr>
<tr><td>异步任务与取消</td><td>下一阶段</td><td>当前快速求解为同步执行。</td></tr>
<tr><td>镜像射线/孔缝腔体插件</td><td>下一阶段</td><td>旧能力未来只通过适配器接入新内核。</td></tr>
</tbody>
</table>
</section>
<section class='card'>
<h2>六、实际使用路径</h2>
<ol>
<li>启动 <code>python run_studio.py</code>；</li>
<li>打开城市动态示例或空白工程；</li>
<li>从对象库添加阵列、运动对象、建筑、接收器或探针；</li>
<li>在属性检查器调整对象位置和旋转；</li>
<li>运行任务；</li>
<li>拖动时间线并观察场切片、轨迹和各对象接收曲线；</li>
<li>保存为 <code>.hpmdt</code> 工程。</li>
</ol>
</section>
<section class='card'>
<h2>七、研究边界</h2>
<ul>
<li>当前后端为归一化自由空间标量格林函数快速模型；</li>
<li>不替代 CST、HFSS 或 COMSOL 的全波求解；</li>
<li>建筑物目前具有场景与可视化语义，尚未进入反射求解；</li>
<li>不输出真实源功率、真实作用距离、现实器件阈值或现实毁伤结论；</li>
<li>本版本是新主干的可运行 Alpha，不冒充已经完成的最终CAE产品。</li>
</ul>
</section>
</main>
</body></html>"""
OUT.write_text(html, encoding="utf-8")
print(OUT)
