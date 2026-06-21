"use strict";

const $ = (id) => document.getElementById(id);
const 图表配置 = {responsive: true, displaylogo: false, locale: "zh-CN", scrollZoom: true};
let 最近数据 = null;
let 插件缓存 = [];

function 忙碌(显示, 文字="正在计算…") {
  $("忙碌文字").textContent = 文字;
  $("忙碌遮罩").classList.toggle("d-none", !显示);
}
function 提示(文字) {
  $("消息正文").textContent = 文字;
  bootstrap.Toast.getOrCreateInstance($("消息提示"), {delay: 3200}).show();
}
async function 请求(地址, 选项={}) {
  const 响应 = await fetch(地址, {headers: {"Content-Type": "application/json"}, ...选项});
  const 数据 = await 响应.json();
  if (!响应.ok) throw new Error(数据.detail || 数据.错误 || `请求失败：${响应.status}`);
  return 数据;
}
function 画图(id, 图形) {
  if (!图形 || !$(id)) return;
  Plotly.react(id, 图形.data, 图形.layout, 图表配置);
}
function 状态颜色(状态) {
  if (["通过","提示"].includes(状态)) return 状态 === "提示" ? "secondary" : "success";
  if (["关注","谨慎"].includes(状态)) return "warning";
  return "danger";
}
function 格式化(x) {
  if (x === null || x === undefined) return "—";
  if (typeof x === "boolean") return `<span class="badge bg-${x ? "success" : "danger"}">${x ? "是" : "否"}</span>`;
  if (typeof x === "number") return Number.isInteger(x) ? String(x) : x.toFixed(6).replace(/0+$/,"").replace(/\.$/,"");
  if (typeof x === "object") return JSON.stringify(x);
  return String(x);
}
function 转义文本(x) {
  return String(x ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}
function 渲染表格(表格, 记录) {
  if (!记录 || !记录.length) { 表格.innerHTML = "<tbody><tr><td class='text-muted'>暂无数据</td></tr></tbody>"; return; }
  const 列 = Object.keys(记录[0]);
  表格.innerHTML = `<thead><tr>${列.map(x=>`<th>${x}</th>`).join("")}</tr></thead><tbody>${记录.map(行=>`<tr>${列.map(x=>`<td>${格式化(行[x])}</td>`).join("")}</tr>`).join("")}</tbody>`;
}
function 渲染键值表(表格, 对象) {
  渲染表格(表格, Object.entries(对象 || {}).map(([指标, 数值]) => ({指标, 数值})));
}
function 渲染插件验收(数据) {
  const 记录 = (数据.验收清单 || []).map(项 => ({
    项目: 项.项目,
    状态: 项.通过 ? "通过" : "待补齐"
  }));
  渲染表格($("插件验收"), 记录);
}
function 渲染插件目录(数据) {
  插件缓存 = 数据.插件 || [];
  if (!插件缓存.length) {
    $("插件目录").innerHTML = "<tbody><tr><td class='text-muted'>暂无插件</td></tr></tbody>";
    return;
  }
  $("插件目录").innerHTML = `<thead><tr><th>插件</th><th>类别</th><th>版本</th><th>状态</th><th>操作</th></tr></thead><tbody>${
    插件缓存.map(插件 => {
      const id = 转义文本(插件.id);
      const enabled = Boolean(插件.已启用);
      const toggleText = enabled ? "禁用" : "启用";
      const toggleClass = enabled ? "outline-warning" : "outline-success";
      return `<tr>
        <td><strong>${转义文本(插件.名称)}</strong><br><span class="text-muted small">${id}</span></td>
        <td>${转义文本(插件.类别)}</td>
        <td>${转义文本(插件.版本)}</td>
        <td><span class="badge bg-${enabled ? "success" : "secondary"}">${enabled ? "已启用" : "已禁用"}</span></td>
        <td class="text-nowrap">
          <button class="btn btn-sm btn-${toggleClass} 插件启停" data-plugin-id="${id}" data-enabled="${enabled ? "false" : "true"}"><i class="bi bi-power"></i> ${toggleText}</button>
          <button class="btn btn-sm btn-outline-primary 插件运行" data-plugin-id="${id}" ${enabled ? "" : "disabled"}><i class="bi bi-play-fill"></i> 运行</button>
        </td>
      </tr>`;
    }).join("")
  }</tbody>`;
}
function 渲染论文工厂状态(数据) {
  if (!$("论文工厂状态")) return;
  const 通过 = Boolean(数据.通过);
  const 清单 = (数据.验收清单 || []).map(项 => `<li><span class="badge bg-${项.通过 ? "success" : "secondary"}">${项.通过 ? "通过" : "待生成"}</span> ${转义文本(项.项目)}</li>`).join("");
  $("论文工厂状态").innerHTML = `
    <div class="p-3">
      <div class="d-flex justify-content-between align-items-center mb-2">
        <strong>${转义文本(数据.名称 || "Paper Factory")}</strong>
        <span class="badge bg-${通过 ? "success" : "warning"}">${转义文本(数据.状态 || "未知")}</span>
      </div>
      <div class="text-muted small mb-2">${转义文本(数据.版本 || "V2.0D-preview")}</div>
      <ul class="paper-factory-checks">${清单}</ul>
    </div>`;
  $("论文工厂输出").textContent = 数据.产物 ? Object.entries(数据.产物).map(([k,v]) => `${k}: ${v}`).join("\n") : "尚未生成论文包。";
}
function 渲染数据导入验收(数据) {
  const 验收 = 数据.验收 || 数据;
  const 记录 = (验收.验收清单 || []).map(项 => ({
    项目: 项.项目,
    状态: 项.通过 ? "通过" : "待补齐"
  }));
  渲染表格($("数据导入验收"), 记录);
}
function 渲染数据导入样例(数据) {
  const 样例 = 数据.样例 || [];
  if (!样例.length) {
    $("数据导入样例").innerHTML = "<tbody><tr><td class='text-muted'>暂无样例</td></tr></tbody>";
    return;
  }
  $("数据导入样例").innerHTML = `<thead><tr><th>样例</th><th>格式</th><th>记录/频点</th><th>单位</th><th>操作</th></tr></thead><tbody>${
    样例.map(item => {
      const id = 转义文本(item.样例ID);
      return `<tr>
        <td><strong>${id}</strong><br><span class="text-muted small">${转义文本(item.名称)}</span></td>
        <td>${转义文本(item.格式)}</td>
        <td>${转义文本(item.频点数 || item.记录数 || 0)}</td>
        <td>${转义文本((item.单位 || []).join(", ") || "—")}</td>
        <td><button class="btn btn-sm btn-outline-primary 数据样例解析" data-sample-id="${id}"><i class="bi bi-search"></i> 解析</button></td>
      </tr>`;
    }).join("")
  }</tbody>`;
}
function 渲染数据导入标定准备(数据) {
  const 标定 = 数据.标定准备 || {};
  const 样例 = 标定.样例 || [];
  if (!$("数据导入标定准备")) return;
  if (!样例.length) {
    $("数据导入标定准备").innerHTML = "<tbody><tr><td class='text-muted'>暂无标定准备度数据</td></tr></tbody>";
    return;
  }
  const 记录 = 样例.map(item => ({
    样例: item.样例ID || item.名称,
    格式: item.格式,
    准备度: item.标定准备度,
    坐标: item.坐标规范化 ? "已规范化" : "待补齐",
    复场: item.复场可用于标定 ? "可用" : "不可用",
    不确定度: item.不确定度可用 ? "可用" : "无",
    校准: item.校准状态可用 ? "可用" : "无",
    阻断项: (item.阻断项 || []).join("；") || "无"
  }));
  渲染表格($("数据导入标定准备"), 记录);
}
function 渲染数据导入标定桥接(数据) {
  if (!$("数据导入标定桥接")) return;
  const 桥接 = 数据 || {};
  if (桥接.错误) {
    渲染表格($("数据导入标定桥接"), [{指标: "错误", 数值: 桥接.错误}]);
    return;
  }
  if (!Object.keys(桥接).length) {
    $("数据导入标定桥接").innerHTML = "<tbody><tr><td class='text-muted'>暂无标定桥接数据</td></tr></tbody>";
    return;
  }
  const 预览 = 桥接.标定预览 || {};
  const 记录 = [
    {指标: "样例", 数值: 桥接.样例ID || "未知"},
    {指标: "样本数", 数值: 桥接.样本数 || 0},
    {指标: "CalibrationSamples", 数值: 桥接["CalibrationSamples兼容"] ? "兼容" : "阻断"},
    {指标: "坐标", 数值: `${桥接.坐标来源单位 || "?"} -> ${桥接.目标坐标 || "lambda"}`},
    {指标: "参考频率/GHz", 数值: 桥接.参考频率GHz ?? "无"},
    {指标: "代理激励", 数值: 桥接.代理激励 || "未生成"},
    {指标: "标定预览", 数值: 预览.执行 ? `已执行，RMSE ${格式化(预览.标定前RMSE)} -> ${格式化(预览.标定后RMSE)}` : "未执行"},
    {指标: "求解状态", 数值: 预览.执行 ? (预览.求解成功 ? "收敛" : "预览完成") : "阻断"},
    {指标: "阻断项", 数值: (桥接.阻断项 || []).join("；") || "无"},
    {指标: "输出文件", 数值: 桥接.输出文件 || "未写入"},
    {指标: "安全边界", 数值: 桥接.安全边界 || ""}
  ];
  渲染表格($("数据导入标定桥接"), 记录);
}
function 渲染数据导入模型误差对比(数据) {
  if (!$("数据导入模型误差")) return;
  const 对比 = 数据 || {};
  if (对比.错误) {
    渲染表格($("数据导入模型误差"), [{指标: "错误", 数值: 对比.错误}]);
    return;
  }
  if (!Object.keys(对比).length) {
    $("数据导入模型误差").innerHTML = "<tbody><tr><td class='text-muted'>暂无模型误差对比数据</td></tr></tbody>";
    return;
  }
  const 误差 = 对比.误差对比 || {};
  const 覆盖 = 对比.不确定度覆盖率 || {};
  const 门槛 = (对比.门槛 || []).map(item => `${item.项目}:${item.通过 ? "通过" : "待补齐"}`).join("；");
  const 记录 = [
    {指标: "样例", 数值: 对比.样例ID || "未知"},
    {指标: "样本数", 数值: 对比.样本数 || 0},
    {指标: "比较对象", 数值: 对比.比较对象 || "未声明"},
    {指标: "后标定相对RMSE/%", 数值: 误差["标定后相对RMSE/%"] ?? "无"},
    {指标: "RMSE改善/%", 数值: 误差["RMSE改善/%"] ?? "无"},
    {指标: "后标定P95残差", 数值: 误差.标定后P95残差 ?? "无"},
    {指标: "2sigma覆盖率/%", 数值: 覆盖["2sigma覆盖率/%"] ?? "无"},
    {指标: "中位归一化残差", 数值: 覆盖.中位归一化残差 ?? "无"},
    {指标: "门槛", 数值: 门槛 || "无"},
    {指标: "阻断项", 数值: (对比.阻断项 || []).join("；") || "无"},
    {指标: "输出文件", 数值: 对比.输出文件 || "未写入"},
    {指标: "安全边界", 数值: 对比.安全边界 || ""}
  ];
  渲染表格($("数据导入模型误差"), 记录);
}
function 渲染数据导入VV审计(数据) {
  if (!$("数据导入VV审计")) return;
  const 审计 = 数据 || {};
  if (审计.错误) {
    渲染表格($("数据导入VV审计"), [{指标: "错误", 数值: 审计.错误}]);
    return;
  }
  if (!Object.keys(审计).length) {
    $("数据导入VV审计").innerHTML = "<tbody><tr><td class='text-muted'>暂无外部数据 V&V 审计数据</td></tr></tbody>";
    return;
  }
  const 策略 = 审计.正式评分策略 || {};
  const 指标 = 审计.关键指标 || {};
  const 分项 = 审计.分项得分 || {};
  const 门槛 = (审计.门槛 || []).map(item => `${item.项目}:${item.通过 ? "通过" : "待补齐"}`).join("；");
  const 风险 = (审计.风险信号 || []).join("；");
  const 记录 = [
    {指标: "样例", 数值: 审计.样例ID || "未知"},
    {指标: "样本数", 数值: 审计.样本数 || 0},
    {指标: "预评分", 数值: `${格式化(审计.预评分)} / 100（${审计.预评分等级 || "D"}）`},
    {指标: "可纳入正式评分", 数值: 审计.可纳入正式可信度评分 ? "是" : "否"},
    {指标: "风险调整预览评分", 数值: 策略.风险调整预览评分 ?? "未给出"},
    {指标: "是否改写正式评分", 数值: 策略.是否改写正式评分 ? "是" : "否"},
    {指标: "标定后相对RMSE/%", 数值: 指标["标定后相对RMSE/%"] ?? "无"},
    {指标: "2sigma覆盖率/%", 数值: 指标["2sigma覆盖率/%"] ?? "无"},
    {指标: "中位归一化残差", 数值: 指标.中位归一化残差 ?? "无"},
    {指标: "分项得分", 数值: JSON.stringify(分项)},
    {指标: "门槛", 数值: 门槛 || "无"},
    {指标: "风险信号", 数值: 风险 || "无"},
    {指标: "输出文件", 数值: 审计.输出文件 || "未写入"},
    {指标: "安全边界", 数值: 审计.安全边界 || ""}
  ];
  渲染表格($("数据导入VV审计"), 记录);
}
async function 载入数据导入() {
  if (!$("数据导入状态")) return;
  try {
    const [数据, 桥接, 模型对比, VVAudit] = await Promise.all([
      请求("/api/data-import/catalog"),
      请求("/api/data-import/calibration-bridge"),
      请求("/api/data-import/model-comparison"),
      请求("/api/data-import/vv-audit")
    ]);
    const 通过 = Boolean(数据.验收 && 数据.验收.通过);
    $("数据导入状态").className = 通过 ? "alert alert-success" : "alert alert-warning";
    $("数据导入状态").textContent = `V3.0 数据导入：${数据.样例数} 个样例，支持 ${数据.支持格式.join(" / ")}。`;
    渲染数据导入验收(数据);
    渲染数据导入样例(数据);
    渲染数据导入标定准备(数据);
    渲染数据导入标定桥接(桥接);
    渲染数据导入模型误差对比(模型对比);
    渲染数据导入VV审计(VVAudit);
  } catch (错误) {
    $("数据导入状态").className = "alert alert-danger";
    $("数据导入状态").textContent = 错误.message;
    渲染数据导入标定桥接({错误: 错误.message});
    渲染数据导入模型误差对比({错误: 错误.message});
    渲染数据导入VV审计({错误: 错误.message});
  }
}
async function 解析数据样例(sampleId) {
  try {
    const 数据 = await 请求(`/api/data-import/samples/${encodeURIComponent(sampleId)}`);
    $("数据导入结果").textContent = JSON.stringify(数据, null, 2);
  } catch (错误) {
    $("数据导入结果").textContent = 错误.message;
    提示(错误.message);
  }
}
async function 解析数据路径() {
  const path = $("数据导入路径").value.trim();
  if (!path) {
    提示("请输入数据文件路径");
    return;
  }
  try {
    const 数据 = await 请求("/api/data-import/inspect", {method: "POST", body: JSON.stringify({path})});
    $("数据导入结果").textContent = JSON.stringify(数据, null, 2);
  } catch (错误) {
    $("数据导入结果").textContent = 错误.message;
    提示(错误.message);
  }
}
async function 载入论文工厂状态() {
  if (!$("论文工厂状态")) return;
  try {
    渲染论文工厂状态(await 请求("/api/paper-factory/status"));
  } catch (错误) {
    $("论文工厂状态").innerHTML = `<div class="alert alert-danger m-3">${转义文本(错误.message)}</div>`;
  }
}
async function 生成论文包() {
  忙碌(true, "正在生成 V2.0D 论文草稿包…");
  try {
    const 数据 = await 请求("/api/paper-factory/generate", {method: "POST", body: JSON.stringify({refresh_vv: false})});
    渲染论文工厂状态(数据);
    提示("论文草稿包已生成");
  } catch (错误) {
    提示(错误.message);
  } finally {
    忙碌(false);
  }
}
async function 载入插件市场() {
  if (!$("插件状态")) return;
  try {
    const [目录, 验收] = await Promise.all([
      请求("/api/plugins/catalog"),
      请求("/api/plugins/acceptance")
    ]);
    $("插件状态").className = 验收.通过 ? "alert alert-success" : "alert alert-warning";
    $("插件状态").textContent = `V2.0C 插件目录：${目录.插件总数} 个插件，${目录.类别总数} 类，启用 ${验收.启用插件数} 个。`;
    渲染插件目录(目录);
    渲染插件验收(验收);
  } catch (错误) {
    $("插件状态").className = "alert alert-danger";
    $("插件状态").textContent = 错误.message;
  }
}
async function 设置插件启用(pluginId, enabled) {
  try {
    await 请求(`/api/plugins/${encodeURIComponent(pluginId)}/enable`, {method: "POST", body: JSON.stringify({enabled})});
    await 载入插件市场();
  } catch (错误) {
    提示(错误.message);
  }
}
async function 运行插件(pluginId) {
  try {
    const 结果 = await 请求(`/api/plugins/${encodeURIComponent(pluginId)}/run`, {method: "POST", body: JSON.stringify({parameters: {}})});
    $("插件运行结果").textContent = JSON.stringify(结果, null, 2);
    提示("插件运行完成");
  } catch (错误) {
    $("插件运行结果").textContent = 错误.message;
    提示(错误.message);
  }
}
function 渲染卡片(卡片) {
  $("指标卡片").innerHTML = 卡片.map(项 => `
    <div class="col-12 col-sm-6 col-xl-2"><div class="metric-card h-100 p-3">
      <div class="d-flex justify-content-between align-items-start">
        <div class="text-muted">${项.标签}</div><span class="badge bg-${状态颜色(项.状态)}">${项.状态}</span>
      </div>
      <div class="value mt-2">${项.数值}</div><div class="hint">${项.说明}</div>
    </div></div>`).join("");
}
function 切换页面(页面名) {
  document.querySelectorAll("[data-page-section]").forEach(x => x.classList.toggle("d-none", x.dataset.pageSection !== 页面名));
  document.querySelectorAll("#主导航 .nav-link").forEach(x => x.classList.toggle("active", x.dataset.page === 页面名));
  if (decodeURIComponent(window.location.hash.slice(1)) !== 页面名) {
    history.replaceState(null, "", `#${encodeURIComponent(页面名)}`);
  }
  window.scrollTo({top: 0, behavior: "smooth"});
  setTimeout(()=>window.dispatchEvent(new Event("resize")),100);
}
function 初始页面() {
  const 页面名 = decodeURIComponent(window.location.hash.slice(1));
  return document.querySelector(`[data-page-section="${CSS.escape(页面名)}"]`) ? 页面名 : "验证总览";
}
function 后端记录(用例) {
  const item = (用例 || []).find(x => x["用例编号"] === "VV-06");
  return item ? item["记录"] : [];
}
function 渲染数据(数据) {
  最近数据 = 数据;
  const 平台名 = 数据.平台愿景 ? 数据.平台愿景["平台名称"] : "HPM-DT";
  $("顶部状态").textContent = `${平台名} 长期 CAE 平台 · ${数据.版本} · 评分 ${数据.评分["可信度评分"]} · ${数据.评分["当前等级"]}级`;
  $("总览提示").className = "alert alert-success";
  $("总览提示").textContent = `V&V 已完成：总测试 ${数据.摘要["总测试数"]}，通过 ${数据.摘要["通过数"]}，失败 ${数据.摘要["失败数"]}。`;
  渲染卡片(数据.卡片);
  渲染表格($("用例表"), 数据.用例.map(x => ({
    编号: x["用例编号"], 用例: x["用例名称"], 类别: x["类别"], 状态: x["通过"] ? "通过" : "失败", 结论: x["结论"]
  })));
  渲染表格($("后端表"), 后端记录(数据.用例));
  渲染键值表($("不确定度表"), 数据.不确定度);
  渲染表格($("敏感性表"), 数据.敏感性);
  $("输出路径").textContent = Object.entries(数据.输出).map(([k,v]) => `${k}: ${v}`).join("\n");
  画图("图_方向图解析对比", 数据.图形["方向图解析对比"]);
  画图("图_误差热图", 数据.图形["误差热图"]);
  画图("图_Green函数幅相误差", 数据.图形["Green函数幅相误差"]);
  画图("图_MUSIC空间谱", 数据.图形["MUSIC空间谱"]);
  画图("图_MVDR零陷方向图", 数据.图形["MVDR零陷方向图"]);
  画图("图_敏感性tornado图", 数据.图形["敏感性tornado图"]);
  画图("图_可信度雷达图", 数据.图形["可信度雷达图"]);
  画图("图_不确定度直方图", 数据.图形["不确定度直方图"]);
}
async function 载入总览() {
  忙碌(true, "正在载入可信度验证结果…");
  try {
    渲染数据(await 请求("/api/vv/overview"));
  } catch (错误) {
    $("总览提示").className = "alert alert-danger";
    $("总览提示").textContent = 错误.message;
    提示(错误.message);
  } finally {
    忙碌(false);
  }
}
async function 运行VV(mode) {
  忙碌(true, mode === "full" ? "正在运行完整V&V…" : "正在运行快速V&V…");
  try {
    const 数据 = await 请求("/api/vv/run", {method: "POST", body: JSON.stringify({mode})});
    渲染数据(数据);
    提示(mode === "full" ? "完整V&V已完成" : "快速V&V已完成");
  } catch (错误) {
    提示(错误.message);
  } finally {
    忙碌(false);
  }
}

window.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("#主导航 .nav-link").forEach(x => x.addEventListener("click", e => { e.preventDefault(); 切换页面(x.dataset.page); }));
  $("运行快速VV").addEventListener("click", () => 运行VV("fast"));
  $("运行完整VV").addEventListener("click", () => 运行VV("full"));
  $("导出HTML报告").addEventListener("click", () => { window.location.href = "/download/vv-report.html"; });
  $("导出LaTeX表格").addEventListener("click", () => { window.location.href = "/download/vv-latex.tex"; });
  $("导出论文图包").addEventListener("click", () => { window.location.href = "/download/vv-results.zip"; });
  $("下载结果ZIP").addEventListener("click", () => { window.location.href = "/download/vv-results.zip"; });
  $("生成论文包").addEventListener("click", 生成论文包);
  $("下载论文包").addEventListener("click", () => { window.location.href = "/download/paper-factory.zip"; });
  $("数据导入刷新").addEventListener("click", 载入数据导入);
  $("数据导入检查路径").addEventListener("click", 解析数据路径);
  $("数据导入样例").addEventListener("click", event => {
    const button = event.target.closest(".数据样例解析");
    if (button) 解析数据样例(button.dataset.sampleId);
  });
  $("插件刷新").addEventListener("click", 载入插件市场);
  $("插件目录").addEventListener("click", event => {
    const toggle = event.target.closest(".插件启停");
    if (toggle) {
      设置插件启用(toggle.dataset.pluginId, toggle.dataset.enabled === "true");
      return;
    }
    const run = event.target.closest(".插件运行");
    if (run) 运行插件(run.dataset.pluginId);
  });
  切换页面(初始页面());
  载入总览();
  载入插件市场();
  载入数据导入();
  载入论文工厂状态();
});
