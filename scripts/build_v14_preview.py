#!/usr/bin/env python3
"""生成 V1.4 Bootstrap 工作台的离线静态预览与截图。"""
from __future__ import annotations

from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from hpm_platform.ui.app_v14 import create_app
from hpm_platform.ui.v14_service import V14WorkbenchService

STATIC = ROOT / "src" / "hpm_platform" / "ui" / "static_v14"
OUT = ROOT / "outputs_v14_ui"
OUT.mkdir(parents=True, exist_ok=True)


def inline_asset(html: str, pattern: str, replacement: str) -> str:
    updated, count = re.subn(pattern, lambda _match: replacement, html, count=1)
    if count != 1:
        raise RuntimeError(f"未找到静态资源标签：{pattern}")
    return updated


def main() -> None:
    project_path = ROOT / "configs" / "cae_project_v14.yaml"
    app = create_app(project_path)
    with TestClient(app) as client:
        response = client.get("/")
        response.raise_for_status()
        html_text = response.text

    bootstrap_css = (STATIC / "vendor" / "bootstrap.min.css").read_text(encoding="utf-8")
    icons_css = (STATIC / "vendor" / "bootstrap-icons.min.css").read_text(encoding="utf-8")
    dashboard_css = (STATIC / "css" / "dashboard.css").read_text(encoding="utf-8")
    bootstrap_js = (STATIC / "vendor" / "bootstrap.bundle.min.js").read_text(encoding="utf-8")
    plotly_js = (STATIC / "vendor" / "plotly.min.js").read_text(encoding="utf-8")

    # Gallery images are hidden in the overview screenshot but browsers still fetch them.
    # Replace all remote-looking TestClient URLs with local data URIs.
    import base64
    for filename in (
        "01_全链路数字孪生架构图.png",
        "02_混合传播后端机理图.png",
        "03_传播后端参数标定闭环图.png",
    ):
        payload = base64.b64encode((STATIC / "img" / filename).read_bytes()).decode("ascii")
        html_text = html_text.replace(f"http://testserver/static/img/{filename}", f"data:image/png;base64,{payload}")
    html_text = re.sub(r'href="http://testserver/static/img/[^"]+\.svg"', 'href="#"', html_text)

    html_text = inline_asset(
        html_text,
        r'<link rel="stylesheet" href="(?:https?://testserver)?/static/vendor/bootstrap\.min\.css">',
        f"<style>{bootstrap_css}</style>",
    )
    html_text = inline_asset(
        html_text,
        r'<link rel="stylesheet" href="(?:https?://testserver)?/static/vendor/bootstrap-icons\.min\.css">',
        f"<style>{icons_css}</style>",
    )
    html_text = inline_asset(
        html_text,
        r'<link rel="stylesheet" href="(?:https?://testserver)?/static/css/dashboard\.css">',
        f"<style>{dashboard_css}</style>",
    )
    html_text = inline_asset(
        html_text,
        r'<script src="(?:https?://testserver)?/static/vendor/bootstrap\.bundle\.min\.js"></script>',
        f"<script>{bootstrap_js}</script>",
    )
    html_text = inline_asset(
        html_text,
        r'<script src="(?:https?://testserver)?/static/vendor/plotly\.min\.js"></script>',
        f"<script>{plotly_js}</script>",
    )
    # Remove live API JavaScript and inject deterministic precomputed overview data.
    html_text = re.sub(r'<script src="(?:https?://testserver)?/static/js/app\.js"></script>', "", html_text, count=1)
    service = V14WorkbenchService(project_path)
    data = service.overview_payload()
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<" + "\\/")
    scene_preview = base64.b64encode((STATIC / "img" / "02_混合传播后端机理图.png").read_bytes()).decode("ascii")
    snapshot_js = f"""
<script>
const 数据={payload};
const 场景预览='data:image/png;base64,{scene_preview}';
const 图表配置={{responsive:true,displaylogo:false,locale:'zh-CN'}};
function 画图(id,fig){{Plotly.newPlot(id,fig.data,fig.layout,图表配置);}}
function 状态颜色(s){{return ['良好','通过','适用'].includes(s)?'success':(s==='关注'?'warning':'danger');}}
function 格式化(x){{if(x===null||x===undefined)return '—';if(typeof x==='boolean')return x?'是':'否';if(typeof x==='number')return Number.isInteger(x)?x:x.toFixed(3);return String(x);}}
window.addEventListener('DOMContentLoaded',()=>{{
 document.getElementById('顶部工程名').textContent=数据.工程名称;
 document.getElementById('模型边界提示').innerHTML=`<i class="bi bi-info-circle-fill me-2 mt-1"></i><div><strong>模型边界：</strong>${{数据.模型边界}}</div>`;
 document.getElementById('指标卡片').innerHTML=数据.卡片.map(项=>`<div class="col-12 col-sm-6 col-xl-3"><div class="card shadow-sm 指标卡 h-100"><div class="card-body"><div class="d-flex justify-content-between align-items-start"><div class="text-muted">${{项.标签}}</div><span class="badge bg-${{状态颜色(项.状态)}} 状态徽章">${{项.状态}}</span></div><div class="数值 mt-2">${{项.数值}}</div><div class="说明 mt-1">${{项.说明}}</div></div></div></div>`).join('');
 const 记录=数据.对象指标; const 列=Object.keys(记录[0]);
 document.getElementById('对象结果表').innerHTML=`<thead><tr>${{列.map(x=>`<th>${{x}}</th>`).join('')}}</tr></thead><tbody>${{记录.map(行=>`<tr>${{列.map(x=>`<td>${{格式化(行[x])}}</td>`).join('')}}</tr>`).join('')}}</tbody>`;
 document.getElementById('总览场景图').innerHTML=`<img src="${{场景预览}}" alt="混合传播后端机理图" style="width:100%;height:520px;object-fit:contain;background:#07111f">`;画图('总览场图',数据.图形.场分布);画图('总览对象图',数据.图形.对象指标);
 document.getElementById('忙碌遮罩').classList.add('d-none');
}});
</script>
"""
    html_text = html_text.replace("</body>", snapshot_js + "</body>")
    snapshot_path = OUT / "v14_工作台静态预览.html"
    snapshot_path.write_text(html_text, encoding="utf-8")

    screenshot_path = OUT / "00_V1.4全中文Bootstrap工作台预览.png"
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/usr/bin/chromium",
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = browser.new_page(viewport={"width": 1680, "height": 1050}, device_scale_factor=1)
        page.on("console", lambda msg: errors.append(f"{msg.type}: {msg.text}") if msg.type == "error" else None)
        page.set_content(html_text, wait_until="load", timeout=180_000)
        page.wait_for_selector("#指标卡片 .指标卡", timeout=180_000)
        page.wait_for_function("document.getElementById('忙碌遮罩').classList.contains('d-none')", timeout=180_000)
        page.wait_for_timeout(2200)
        page.screenshot(path=str(screenshot_path), full_page=True)
        cards = page.locator("#指标卡片 .指标卡").count()
        browser.close()
    if errors:
        raise RuntimeError("浏览器控制台错误：" + " | ".join(errors))
    print(json.dumps({
        "静态预览": str(snapshot_path),
        "截图": str(screenshot_path),
        "指标卡数量": cards,
        "截图字节数": screenshot_path.stat().st_size,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
