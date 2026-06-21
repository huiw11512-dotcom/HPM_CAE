"use strict";

const $ = (id) => document.getElementById(id);
const 图表配置 = {responsive: true, displaylogo: false, locale: "zh-CN", scrollZoom: true};
let 最近数据 = null;
let 最近日志 = [];

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
function 画图(容器, 图形) {
  if (!图形) return;
  Plotly.react(容器, 图形.data, 图形.layout, 图表配置);
}
function 更新日志(日志) {
  if (Array.isArray(日志)) 最近日志 = 日志;
  $("日志窗口").textContent = 最近日志.length ? 最近日志.join("\n") : "尚无日志。";
}
function 值(id) { return parseFloat($(id).value); }
function 状态颜色(状态) {
  if (["良好","通过","适用","标定成功"].includes(状态)) return "success";
  if (["关注","谨慎","提示"].includes(状态)) return "warning";
  return "danger";
}
function 渲染指标卡(卡片) {
  $("指标卡片").innerHTML = 卡片.map((项,序号) => `
    <div class="col-12 col-sm-6 col-xl-3"><div class="card shadow-sm 指标卡 h-100">
      <div class="card-body"><div class="d-flex justify-content-between align-items-start">
        <div class="text-muted">${项.标签}</div><span class="badge bg-${状态颜色(项.状态)} 状态徽章">${项.状态}</span>
      </div><div class="数值 mt-2">${项.数值}</div><div class="说明 mt-1">${项.说明}</div></div>
    </div></div>`).join("");
}
function 渲染表格(表格, 记录) {
  if (!记录 || !记录.length) { 表格.innerHTML = "<tbody><tr><td class='text-muted'>暂无数据</td></tr></tbody>"; return; }
  const 列 = Object.keys(记录[0]);
  表格.innerHTML = `<thead><tr>${列.map(x=>`<th>${x}</th>`).join("")}</tr></thead><tbody>${记录.map(行=>`<tr>${列.map(x=>`<td>${格式化(行[x])}</td>`).join("")}</tr>`).join("")}</tbody>`;
}
function 格式化(x) {
  if (x === null || x === undefined || (typeof x === "number" && !Number.isFinite(x))) return "—";
  if (typeof x === "boolean") return `<span class="badge bg-${x ? "success" : "secondary"}">${x ? "是" : "否"}</span>`;
  if (typeof x === "number") return Number.isInteger(x) ? x : x.toFixed(4).replace(/0+$/,"").replace(/\.$/,"");
  return String(x);
}
function 渲染键值表(表格, 对象) {
  const 记录 = Object.entries(对象).map(([指标,数值])=>({指标,数值}));
  渲染表格(表格, 记录);
}
function 更新范围标签() {
  ["直达尺度","反射尺度","腔体尺度"].forEach(id => $(id+"值").textContent = Number($(id).value).toFixed(2));
}
function 切换页面(页面名) {
  document.querySelectorAll("[data-page-section]").forEach(x => x.classList.toggle("d-none", x.dataset.pageSection !== 页面名));
  document.querySelectorAll("#主导航 .nav-link").forEach(x => x.classList.toggle("active", x.dataset.page === 页面名));
  window.scrollTo({top: 0, behavior: "smooth"});
  setTimeout(()=>window.dispatchEvent(new Event("resize")),100);
}

async function 载入总览() {
  忙碌(true,"正在载入工程并执行快速求解…");
  try {
    const 数据 = await 请求("/api/overview"); 最近数据 = 数据;
    $("顶部工程名").textContent = 数据.工程名称;
    $("模型边界提示").innerHTML = `<i class="bi bi-info-circle-fill me-2 mt-1"></i><div><strong>模型边界：</strong>${数据.模型边界}</div>`;
    渲染指标卡(数据.卡片);
    画图("总览场景图",数据.图形.场景); 画图("总览场图",数据.图形.场分布); 画图("总览对象图",数据.图形.对象指标);
    画图("求解场图",数据.图形.场分布); 画图("求解裕量图",数据.图形.约束裕量); 画图("求解权值图",数据.图形.阵元权值);
    渲染表格($("对象结果表"),数据.对象指标); 更新日志(数据.运行日志);
  } catch (错误) { 提示(错误.message); } finally { 忙碌(false); }
}
async function 运行求解() {
  忙碌(true,"正在计算归一化场分布…");
  try {
    const 数据 = await 请求("/api/solve", {method:"POST", body:JSON.stringify({
      backend: $("求解后端").value, solver_method: $("求解方法").value,
      direct_scale: 值("直达尺度"), reflection_scale: 值("反射尺度"), cavity_scale: 值("腔体尺度"), fast: true
    })});
    画图("求解场图",数据.图形.场分布); 画图("求解裕量图",数据.图形.约束裕量); 画图("求解权值图",数据.图形.阵元权值);
    $("求解提示").className="alert alert-success";
    $("求解提示").textContent=`求解完成：目标区 RMSE ${数据.指标.target_rmse_percent.toFixed(2)}%，最低覆盖率 ${数据.指标.minimum_target_coverage_percent.toFixed(1)}%，适用性 ${数据.适用性得分.toFixed(1)} 分。`;
    更新日志(数据.运行日志); 提示("静态求解已完成");
  } catch (错误) { $("求解提示").className="alert alert-danger"; $("求解提示").textContent=错误.message; } finally { 忙碌(false); }
}
async function 运行后端对比() {
  忙碌(true,"正在依次运行四种传播后端…");
  try {
    const 数据=await 请求("/api/compare",{method:"POST",body:JSON.stringify({backends:["free_space_green","image_ray","aperture_cavity_rom","hybrid_scene"]})});
    画图("后端场图",数据.图形.场图对比); 画图("后端指标图",数据.图形.指标对比); 渲染表格($("后端对比表"),数据.记录);
    $("后端对比提示").className="alert alert-success"; $("后端对比提示").textContent="四种传播后端对比完成。请同时查看场分布差异、目标区误差、保护区裕量与运行耗时。";
    更新日志(数据.运行日志); 提示("传播后端对比完成");
  } catch(错误){ $("后端对比提示").className="alert alert-danger"; $("后端对比提示").textContent=错误.message; } finally { 忙碌(false); }
}
async function 运行适用性() {
  忙碌(true,"正在检查数值模型适用范围…");
  try {
    const 数据=await 请求("/api/validity",{method:"POST",body:JSON.stringify({backend:$("适用性后端").value})});
    画图("适用性图",数据.图形); 渲染表格($("适用性表"),数据.报告.检查项); 更新日志(数据.运行日志); 提示(`适用性诊断完成：${数据.报告.适用性得分.toFixed(1)} 分`);
  } catch(错误){提示(错误.message);} finally {忙碌(false);}
}
async function 运行标定() {
  忙碌(true,"正在标定直达、反射与腔体尺度…");
  try {
    const 数据=await 请求("/api/calibrate",{method:"POST",body:JSON.stringify({
      reference_backend:$("参考后端").value,candidate_backend:$("待标定后端").value,
      reference_scales:[值("参考直达"),值("参考反射"),值("参考腔体")],initial_scales:[值("初始直达"),值("初始反射"),值("初始腔体")],
      samples_per_axis:parseInt($("标定采样").value),noise_percent:值("标定噪声")
    })});
    画图("标定总览图",数据.图形.标定总览); 画图("标定场图",数据.图形.空间复核); 渲染键值表($("标定摘要表"),数据.摘要);
    $("标定提示").className=`alert alert-${数据.成功?"success":"warning"}`;
    $("标定提示").textContent=`标定完成：相对 RMSE ${数据.摘要["标定前相对RMSE/%"].toFixed(2)}% → ${数据.摘要["标定后相对RMSE/%"].toFixed(3)}%，改善 ${数据.摘要["RMSE改善/%"].toFixed(2)}%。`;
    更新日志(数据.运行日志); 提示("传播尺度参数标定完成");
  } catch(错误){ $("标定提示").className="alert alert-danger"; $("标定提示").textContent=错误.message; } finally {忙碌(false);}
}

window.addEventListener("DOMContentLoaded",()=>{
  document.querySelectorAll("#主导航 .nav-link").forEach(x=>x.addEventListener("click",e=>{e.preventDefault();切换页面(x.dataset.page);}));
  ["直达尺度","反射尺度","腔体尺度"].forEach(id=>$(id).addEventListener("input",更新范围标签)); 更新范围标签();
  $("刷新总览").addEventListener("click",载入总览); $("运行求解").addEventListener("click",运行求解); $("运行后端对比").addEventListener("click",运行后端对比);
  $("运行适用性").addEventListener("click",运行适用性); $("运行标定").addEventListener("click",运行标定); $("刷新日志").addEventListener("click",()=>更新日志(最近日志));
  载入总览().then(()=>运行适用性());
});
