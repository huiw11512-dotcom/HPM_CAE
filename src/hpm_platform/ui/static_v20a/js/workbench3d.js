import * as THREE from "../vendor/three.module.min.js";

"use strict";

const $ = (id) => document.getElementById(id);
const colors = {
  array: 0x35d8ff,
  plane: 0x86a7ff,
  target: 0xffc857,
  protected: 0x4ee0a5,
  reflector: 0xc8d4e8,
  cavity: 0xab8cff,
  aperture: 0xff7aa2,
  source: 0xff6b7a,
  echo: 0x9f7aea,
  grid: 0x2b394d,
  selected: 0xffffff,
};

let sceneData = null;
let selectedId = null;
let selectedMaterialId = null;
let solveData = null;
let solveArchive = [];
let solveJobs = [];
let solveJobAudit = {};
let snapshotArchive = [];
let snapshotDiff = null;
let assetLedger = [];
let assetLedgerSummary = {};
let assetLedgerAudit = {};
let assetDatabaseAudit = {};
let assetDatabaseRecords = {};
let assetLineage = {};
let assetNamingAudit = {};
let assetReproducibilityAudit = {};
let assetAbsoluteCalibration = {};
let assetImportedCalibration = {};
let assetMaterialAudit = {};
let absoluteCalibration = {};
let assetLedgerFilter = {type: "全部", query: ""};
let profileAxis = "x";
let scene = null;
let camera = null;
let renderer = null;
let root = null;
let selectionBox = null;
let resultOverlay = null;
let raycaster = null;
let pointer = null;
const objectGroups = new Map();
const orbit = {
  target: new THREE.Vector3(0, 0, 4),
  radius: 14,
  theta: -0.78,
  phi: 0.58,
};
let isDragging = false;
let dragStart = {x: 0, y: 0, theta: 0, phi: 0};
let moveMode = false;
let activeMove = null;
const dragPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
const dragPoint = new THREE.Vector3();
const draggableTypes = new Set(["target_region", "protected_zone", "cavity_rom", "aperture"]);

function status(text, kind = "info") {
  const node = $("三维状态");
  if (!node) return;
  node.className = `alert alert-${kind}`;
  node.textContent = text;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {headers: {"Content-Type": "application/json"}, ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `请求失败：${response.status}`);
  return data;
}

function sceneObjectById(objectId) {
  return sceneData ? sceneData["对象"].find((item) => item.id === objectId) : null;
}

function materialLibrary() {
  return sceneData ? sceneData["材料库"] || [] : [];
}

function materialById(materialId) {
  return materialLibrary().find((item) => item.id === materialId) || null;
}

function escapeAttr(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function selectedMaterialFor(item) {
  if (selectedMaterialId && materialById(selectedMaterialId)) return selectedMaterialId;
  if (item && item["材料"] && materialById(item["材料"])) {
    selectedMaterialId = item["材料"];
    return selectedMaterialId;
  }
  const first = materialLibrary()[0];
  selectedMaterialId = first ? first.id : null;
  return selectedMaterialId;
}

function isDraggableObject(item) {
  const editable = new Set(item ? item["可编辑字段"] || [] : []);
  return Boolean(item && item["启用"] && draggableTypes.has(item["类型"]) && editable.has("center_x_lambda") && editable.has("center_y_lambda"));
}

function snapLambda(value) {
  return Math.round(value / 0.05) * 0.05;
}

function updateHistoryControls() {
  const history = sceneData ? sceneData["历史"] || {} : {};
  const undo = $("三维撤销");
  const redo = $("三维重做");
  if (undo) undo.disabled = !history["可撤销"];
  if (redo) redo.disabled = !history["可重做"];
}

function formatMetric(value, suffix = "", digits = 2) {
  if (typeof value === "boolean") return value ? "通过" : "关注";
  if (typeof value === "number" && Number.isFinite(value)) return `${value.toFixed(digits)}${suffix}`;
  if (value === null || value === undefined) return "--";
  return `${value}${suffix}`;
}

function objectMetricStatus(row) {
  return Number(row.success) === 1 ? "通过" : "关注";
}

function objectMetricSummary(row) {
  if (row.object_type === "target") {
    return `RMSE ${formatMetric(row.rmse_percent, "%")} · 覆盖 ${formatMetric(row.coverage_percent, "%")} · 峰值 ${formatMetric(row.peak_db, " dB")}`;
  }
  if (row.object_type === "protected") {
    return `p95 ${formatMetric(row.p95_db, " dB")} · 峰值 ${formatMetric(row.peak_db, " dB")} · 超限 ${formatMetric(row.violation_db, " dB")}`;
  }
  return `均值 ${formatMetric(row.mean_amplitude)} · 成功 ${objectMetricStatus(row)}`;
}

function objectMetricBadgeText(row) {
  if (row.object_type === "target") return `RMSE ${formatMetric(row.rmse_percent, "%")} / 覆盖 ${formatMetric(row.coverage_percent, "%")}`;
  if (row.object_type === "protected") return `p95 ${formatMetric(row.p95_db, " dB")} / 超限 ${formatMetric(row.violation_db, " dB")}`;
  return objectMetricSummary(row);
}

function renderObjectMetrics() {
  const rows = solveData ? solveData["对象指标"] || [] : [];
  if (!rows.length) return "";
  return `
    <div class="workbench3d-object-metrics" data-testid="workbench3d-object-metrics">
      ${rows.map((row) => `
        <button type="button" class="${objectMetricStatus(row) === "通过" ? "ok" : "warn"}" data-metric-object-id="${escapeAttr(row.object_id)}">
          <strong>${escapeAttr(row.name || row.object_id || "--")}</strong>
          <small>${escapeAttr(row.object_id || "--")} · ${escapeAttr(row.object_type || "--")} · ${objectMetricStatus(row)}</small>
          <span>${escapeAttr(objectMetricSummary(row))}</span>
        </button>`).join("")}
    </div>`;
}

function validityStatusClass(status) {
  if (status === "适用") return "ok";
  if (status === "提示") return "info";
  if (status === "谨慎") return "warn";
  if (status === "越界") return "danger";
  return "info";
}

function validityScoreClass(score) {
  if (typeof score !== "number" || !Number.isFinite(score)) return "info";
  if (score >= 90) return "ok";
  if (score >= 78) return "info";
  if (score >= 55) return "warn";
  return "danger";
}

function validityCounts(checks) {
  const counts = {"适用": 0, "提示": 0, "谨慎": 0, "越界": 0};
  checks.forEach((item) => {
    const status = item["状态"];
    counts[status] = (counts[status] || 0) + 1;
  });
  return counts;
}

function renderValidityDiagnostics() {
  const validity = solveData ? solveData["适用性"] || {} : {};
  const checks = Array.isArray(validity["检查项"]) ? validity["检查项"] : [];
  const score = finiteNumber(validity["适用性得分"]);
  if (!checks.length && score === null) return "";
  const counts = validityCounts(checks);
  const focusRows = checks.filter((item) => item["状态"] !== "适用");
  const rows = (focusRows.length ? focusRows : checks).slice(0, 5);
  return `
    <div class="workbench3d-validity-diagnostics" data-testid="workbench3d-validity-diagnostics">
      <div class="workbench3d-validity-score ${validityScoreClass(score)}">
        <small>V&V适用性</small>
        <strong>${formatMetric(score, " 分", 1)}</strong>
        <span>${escapeAttr(validity["结论"] || "--")}</span>
      </div>
      <div class="workbench3d-validity-body">
        <div class="workbench3d-validity-chips">
          <span>后端 ${escapeAttr(validity["传播后端"] || "--")}</span>
          <span>适用 ${counts["适用"] || 0}</span>
          <span>提示 ${counts["提示"] || 0}</span>
          <span>谨慎 ${counts["谨慎"] || 0}</span>
          <span>越界 ${counts["越界"] || 0}</span>
        </div>
        <p>${escapeAttr(validity["摘要"] || "当前求解结果附带归一化模型适用性审计。")}</p>
        <div class="workbench3d-validity-checks">
          ${rows.map((item) => `
            <div class="${validityStatusClass(item["状态"])}" data-validity-status="${escapeAttr(item["状态"] || "--")}">
              <strong>${escapeAttr(item["检查项"] || "--")}</strong>
              <small>${escapeAttr(item["类别"] || "--")} · ${escapeAttr(item["状态"] || "--")} · 当前 ${escapeAttr(item["当前值"] || "--")}</small>
              <span>${escapeAttr(item["建议范围"] || "--")}</span>
            </div>`).join("")}
        </div>
      </div>
    </div>`;
}

function renderSolveResult() {
  const panel = $("三维求解结果");
  if (!panel) return;
  if (!solveData) {
    panel.textContent = "尚未运行三维联动求解。";
    return;
  }
  const summary = solveData["摘要"] || {};
  const solver = solveData["求解器"] || {};
  const checks = solveData["验收清单"] || [];
  const resultLayer = solveData["结果图层"] || {};
  const resultRecord = solveData["结果档案"] || {};
  const cards = [
    ["目标RMSE", formatMetric(summary.target_rmse_percent, "%")],
    ["最低覆盖率", formatMetric(summary.minimum_target_coverage_percent, "%")],
    ["区外峰值", formatMetric(summary.peak_outside_db, " dB")],
    ["保护区超限", formatMetric(summary.maximum_protected_violation_db, " dB")],
  ];
  panel.innerHTML = `
    <div class="workbench3d-solve-grid">
      ${cards.map(([label, value]) => `<div class="workbench3d-solve-metric"><small>${label}</small><strong>${value}</strong></div>`).join("")}
    </div>
    <div class="workbench3d-solve-meta">
      <span>${solveData["阶段"]}</span>
      <span>${solver["传播后端"] || "--"}</span>
      <span>${solver["方法"] || "--"}</span>
      <span>result_id ${solveData.result_id || resultRecord.id || "--"}</span>
      <span>scene_hash ${solveData.scene_hash || "--"}</span>
      <span>field_hash ${resultLayer.field_hash || "--"}</span>
      <span>耗时 ${formatMetric(summary.solver_runtime_ms, " ms", 1)}</span>
    </div>
    ${renderResultDiagnostics(resultLayer)}
    ${renderValidityDiagnostics()}
    ${renderObjectMetrics()}
    <div class="workbench3d-solve-checks">
      ${checks.map((item) => `<span>${item["项目"]}：${item["状态"]}</span>`).join("")}
    </div>`;
}

function profileSummary(values) {
  if (!Array.isArray(values) || values.length === 0) return "--";
  const positions = [0, 0.25, 0.5, 0.75, 1].map((ratio) => Math.round(ratio * (values.length - 1)));
  return [...new Set(positions)].map((index) => formatMetric(Number(values[index]), " dB", 1)).join(" / ");
}

function finiteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function profileSeries(layer) {
  const profile = layer["剖面"] || {};
  const axis = profileAxis === "y" ? "y" : "x";
  const values = axis === "x" ? profile.x_cut_db : profile.y_cut_db;
  const coordinates = axis === "x" ? layer.x_lambda : layer.y_lambda;
  const fixedCoordinate = axis === "x" ? finiteNumber(profile.x_cut_y_lambda) : finiteNumber(profile.y_cut_x_lambda);
  const fixedLabel = axis === "x"
    ? `固定 y=${formatMetric(fixedCoordinate, " λ", 2)}`
    : `固定 x=${formatMetric(fixedCoordinate, " λ", 2)}`;
  return {
    axis,
    values: Array.isArray(values) ? values.map((value) => Number(value)) : [],
    coordinates: Array.isArray(coordinates) ? coordinates.map((value) => Number(value)) : [],
    fixedLabel,
  };
}

function profileRange(values) {
  const finiteValues = values.filter((value) => Number.isFinite(value));
  if (!finiteValues.length) return {min: null, max: null};
  return {min: Math.min(...finiteValues), max: Math.max(...finiteValues)};
}

function profileChartScale(layer, values) {
  const scale = layer["色标"] || {};
  const local = profileRange(values);
  let minValue = finiteNumber(scale["最小值"]);
  let maxValue = finiteNumber(scale["最大值"]);
  if (minValue === null || maxValue === null || maxValue <= minValue) {
    minValue = local.min;
    maxValue = local.max;
  }
  if (minValue === null || maxValue === null) return {minValue: 0, maxValue: 1, local};
  if (maxValue === minValue) {
    minValue -= 1;
    maxValue += 1;
  }
  return {minValue, maxValue, local};
}

function profileSvgPoint(value, index, total, minValue, maxValue, width = 340, height = 112) {
  if (!Number.isFinite(value)) return null;
  const plot = {left: 10, right: 10, top: 8, bottom: 16};
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const x = plot.left + (plotWidth * index) / Math.max(total - 1, 1);
  const ratio = (Math.max(minValue, Math.min(maxValue, value)) - minValue) / Math.max(maxValue - minValue, 1e-9);
  const y = plot.top + plotHeight * (1 - ratio);
  return {x, y};
}

function profilePath(values, minValue, maxValue, width = 340, height = 112) {
  const points = values
    .map((value, index) => profileSvgPoint(value, index, values.length, minValue, maxValue, width, height))
    .filter(Boolean);
  if (!points.length) return "";
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(" ");
}

function profilePeak(values) {
  let peak = {index: -1, value: null};
  values.forEach((value, index) => {
    if (!Number.isFinite(value)) return;
    if (peak.value === null || value > peak.value) peak = {index, value};
  });
  return peak;
}

function renderProfileInspector(layer) {
  const series = profileSeries(layer);
  const {minValue, maxValue, local} = profileChartScale(layer, series.values);
  const path = profilePath(series.values, minValue, maxValue);
  if (!path) return "";
  const peak = profilePeak(series.values);
  const peakPoint = peak.index >= 0 ? profileSvgPoint(peak.value, peak.index, series.values.length, minValue, maxValue) : null;
  const axisLabel = series.axis === "x" ? "x剖面" : "y剖面";
  const coord = peak.index >= 0 ? finiteNumber(series.coordinates[peak.index]) : null;
  const startCoord = finiteNumber(series.coordinates[0]);
  const endCoord = finiteNumber(series.coordinates[series.coordinates.length - 1]);
  return `
    <div class="workbench3d-profile-inspector" data-testid="workbench3d-profile-inspector">
      <div class="workbench3d-profile-toolbar">
        <div class="workbench3d-profile-title">
          <strong>${axisLabel}曲线</strong>
          <small>${escapeAttr(series.fixedLabel)}</small>
        </div>
        <div class="workbench3d-profile-tabs" role="tablist" aria-label="剖面方向">
          <button type="button" class="${series.axis === "x" ? "active" : ""}" data-profile-axis="x" aria-selected="${series.axis === "x"}">x剖面</button>
          <button type="button" class="${series.axis === "y" ? "active" : ""}" data-profile-axis="y" aria-selected="${series.axis === "y"}">y剖面</button>
        </div>
      </div>
      <svg class="workbench3d-profile-chart" viewBox="0 0 340 112" role="img" aria-label="${escapeAttr(axisLabel)}归一化场强曲线">
        <rect x="0" y="0" width="340" height="112" rx="6" fill="#f8fafc"></rect>
        <line x1="10" y1="8" x2="330" y2="8" stroke="#dbe3ef" stroke-width="1"></line>
        <line x1="10" y1="52" x2="330" y2="52" stroke="#dbe3ef" stroke-width="1"></line>
        <line x1="10" y1="96" x2="330" y2="96" stroke="#dbe3ef" stroke-width="1"></line>
        <path d="${path}" fill="none" stroke="#2563eb" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"></path>
        ${peakPoint ? `<circle cx="${peakPoint.x.toFixed(2)}" cy="${peakPoint.y.toFixed(2)}" r="3.6" fill="#cc3d4a"></circle>` : ""}
      </svg>
      <div class="workbench3d-profile-meta">
        <span>样本 ${series.values.length}</span>
        <span>曲线范围 ${formatMetric(local.min, " dB", 1)} / ${formatMetric(local.max, " dB", 1)}</span>
        <span>峰值 ${formatMetric(peak.value, " dB", 1)} @ ${series.axis}=${formatMetric(coord, " λ", 2)}</span>
        <span>坐标 ${formatMetric(startCoord, " λ", 2)} -> ${formatMetric(endCoord, " λ", 2)}</span>
      </div>
    </div>`;
}

function renderResultDiagnostics(layer) {
  if (!layer || layer["类型"] !== "observation_field_db") return "";
  const scale = layer["色标"] || {};
  const stats = layer["统计"] || {};
  const profile = layer["剖面"] || {};
  const peak = stats["峰值坐标"] || {};
  return `
    <div class="workbench3d-result-diagnostics" data-testid="workbench3d-result-diagnostics">
      <div class="workbench3d-result-legend">
        <span>${formatMetric(scale["最小值"], " dB", 0)}</span>
        <div class="workbench3d-result-colorbar" aria-hidden="true"></div>
        <span>${formatMetric(scale["最大值"], " dB", 0)}</span>
      </div>
      <div class="workbench3d-profile-grid">
        <span>范围 ${formatMetric(stats["最小值"], " dB", 1)} / ${formatMetric(stats["最大值"], " dB", 1)}</span>
        <span>平均 ${formatMetric(stats["平均值"], " dB", 1)}</span>
        <span>峰值 λ(${formatMetric(peak.x_lambda, "", 2)}, ${formatMetric(peak.y_lambda, "", 2)})</span>
        <span>x剖面 ${profileSummary(profile.x_cut_db)}</span>
        <span>y剖面 ${profileSummary(profile.y_cut_db)}</span>
      </div>
      ${renderProfileInspector(layer)}
    </div>`;
}

function renderResultArchive() {
  const panel = $("三维结果档案");
  if (!panel) return;
  if (!solveArchive.length) {
    panel.textContent = "尚无三维求解结果档案。运行求解后会自动保存可复查 JSON。";
    return;
  }
  const rows = [...solveArchive].slice(-5).reverse();
  panel.innerHTML = `
    <div class="workbench3d-result-archive-list">
      ${rows.map((item) => `
        <div class="workbench3d-result-record">
          <div>
            <strong>${item.id}</strong>
            <small>${item["创建时间"] || "--"} · 修订 ${item["修订"] ?? "--"}</small>
          </div>
          <div>
            <small>scene_hash ${item.scene_hash || "--"} · field_hash ${item.field_hash || "--"}</small>
            <small>RMSE ${formatMetric(item["目标RMSE"], "%")} · 覆盖 ${formatMetric(item["最低覆盖率"], "%")} · 区外 ${formatMetric(item["区外峰值"], " dB")}</small>
          </div>
          <div class="workbench3d-result-record-actions">
            <button type="button" data-result-action="review" data-result-id="${escapeAttr(item.id)}">复查</button>
            <button type="button" data-result-action="export" data-result-id="${escapeAttr(item.id)}">导出</button>
          </div>
        </div>`).join("")}
    </div>`;
}

function solveJobClass(row) {
  if (row["状态"] === "已完成") return "done";
  if (row["状态"] === "失败") return "failed";
  if (row["状态"] === "已取消") return "cancelled";
  if (row["状态"] === "已暂停") return "paused";
  return "running";
}

function solveJobStatusSummary() {
  const counts = solveJobAudit["状态计数"] || {};
  const rows = Object.entries(counts).map(([key, value]) => `${key} ${value}`);
  if (!rows.length && solveJobs.length) rows.push(`任务 ${solveJobs.length}`);
  return rows.join(" · ") || "暂无任务";
}

function renderSolveJobs() {
  const panel = $("三维求解任务");
  if (!panel) return;
  const auditLabel = solveJobAudit["结论"] || "--";
  const auditClass = solveJobAudit["通过"] === false ? "warn" : "ok";
  if (!solveJobs.length) {
    panel.innerHTML = `
      <div class="workbench3d-solve-job-audit ${auditClass}" data-testid="workbench3d-solve-job-audit">
        <span>审计 ${escapeAttr(auditLabel)}</span>
        <span>${escapeAttr(solveJobStatusSummary())}</span>
        <button type="button" data-job-action="background">后台</button>
        <button type="button" data-job-action="audit">审计</button>
      </div>
      <div class="workbench3d-solve-job-empty">尚无三维求解任务。运行求解后会生成 JOB-xxxx 任务记录。</div>`;
    return;
  }
  const rows = [...solveJobs].slice(-5).reverse();
  panel.innerHTML = `
    <div class="workbench3d-solve-job-audit ${auditClass}" data-testid="workbench3d-solve-job-audit">
      <span>审计 ${escapeAttr(auditLabel)}</span>
      <span>总数 ${solveJobAudit["任务总数"] ?? solveJobs.length}</span>
      <span>${escapeAttr(solveJobStatusSummary())}</span>
      <span>最新 ${escapeAttr(solveJobAudit["最新任务"] || rows[0]?.id || "--")}</span>
      <button type="button" data-job-action="background">后台</button>
      <button type="button" data-job-action="audit">审计</button>
    </div>
    <div class="workbench3d-solve-job-list">
      ${rows.map((item) => `
        <div class="workbench3d-solve-job ${solveJobClass(item)}">
          <div>
            <strong>${escapeAttr(item.id || "--")}</strong>
            <small>${escapeAttr(item["状态"] || "--")} · 修订 ${item["修订"] ?? "--"}</small>
          </div>
          <div>
            <small>${escapeAttr(item["标签"] || "--")} · result_id ${escapeAttr(item.result_id || "--")}</small>
            <small>scene_hash ${escapeAttr(item.scene_hash || "--")} · field_hash ${escapeAttr(item.field_hash || "--")}</small>
            <small>RMSE ${formatMetric(item["目标RMSE"], "%")} · 覆盖 ${formatMetric(item["最低覆盖率"], "%")} · 区外 ${formatMetric(item["区外峰值"], " dB")}</small>
          </div>
          <div class="workbench3d-solve-job-actions">
            <button type="button" data-job-action="inspect" data-job-id="${escapeAttr(item.id || "")}">详情</button>
            <button type="button" data-job-action="review" data-result-id="${escapeAttr(item.result_id || "")}" ${item.result_id ? "" : "disabled"}>复查</button>
            <button type="button" data-job-action="retry" data-job-id="${escapeAttr(item.id || "")}">重试</button>
            <button type="button" data-job-action="pause" data-job-id="${escapeAttr(item.id || "")}" ${["排队中", "运行中"].includes(item["状态"]) ? "" : "disabled"}>暂停</button>
            <button type="button" data-job-action="resume" data-job-id="${escapeAttr(item.id || "")}" ${item["状态"] === "已暂停" ? "" : "disabled"}>恢复</button>
            <button type="button" data-job-action="cancel" data-job-id="${escapeAttr(item.id || "")}" ${["排队中", "运行中", "已暂停"].includes(item["状态"]) ? "" : "disabled"}>取消</button>
          </div>
        </div>`).join("")}
    </div>`;
}

async function loadSolveJobs() {
  const data = await requestJson("/api/workbench3d/solve-jobs");
  solveJobs = data["任务"] || [];
  solveJobAudit = data["审计"] || {};
  if (sceneData && data["历史"]) {
    sceneData["历史"] = data["历史"];
    updateHistoryControls();
  }
  renderSolveJobs();
}

async function auditSolveJobs() {
  const data = await requestJson("/api/workbench3d/solve-jobs/audit");
  solveJobs = data["任务"] || solveJobs;
  solveJobAudit = data["审计"] || {};
  renderSolveJobs();
  status(`求解任务审计${solveJobAudit["结论"] || "--"}：任务 ${solveJobAudit["任务总数"] ?? solveJobs.length} 条。`, solveJobAudit["通过"] === false ? "warning" : "success");
}

async function submitBackgroundSolveJob() {
  const data = await requestJson("/api/workbench3d/solve-jobs", {
    method: "POST",
    body: JSON.stringify({
      label: `后台检查点-${new Date().toLocaleTimeString("zh-CN", {hour12: false})}`,
      background: true,
      start_paused: true,
    }),
  });
  solveJobs = data["队列"] || solveJobs;
  solveJobAudit = data["审计"] || solveJobAudit;
  renderSolveJobs();
  await loadAssetLedger();
  status(`已创建后台求解检查点 ${data["任务"]?.id || "--"}，可在任务队列中恢复或取消。`, "success");
}

async function loadResultArchive() {
  const data = await requestJson("/api/workbench3d/results");
  solveArchive = data["结果"] || [];
  if (sceneData && data["历史"]) {
    sceneData["历史"] = data["历史"];
    updateHistoryControls();
  }
  renderResultArchive();
}

async function inspectSolveJob(jobId) {
  const detail = await requestJson(`/api/workbench3d/solve-jobs/${encodeURIComponent(jobId)}`);
  const result = detail["结果"];
  if (result) {
    solveData = result;
    renderSolveResult();
    renderResultOverlay();
  }
  const task = detail["任务"] || {};
  status(`已载入求解任务 ${jobId}：${task["状态"] || "--"}。`, "success");
}

async function retrySolveJob(jobId) {
  status(`正在重试求解任务 ${jobId}。`, "info");
  const data = await requestJson(`/api/workbench3d/solve-jobs/${encodeURIComponent(jobId)}/retry`, {method: "POST"});
  solveJobs = data["队列"] || solveJobs;
  solveJobAudit = data["审计"] || solveJobAudit;
  solveData = data["结果"] || solveData;
  renderSolveResult();
  renderResultOverlay();
  renderSolveJobs();
  await loadResultArchive();
  await loadAssetLedger();
  status(`已生成重试任务 ${data["操作"]?.["新任务"] || data["任务"]?.id || "--"}。`, "success");
}

async function cancelSolveJob(jobId) {
  const data = await requestJson(`/api/workbench3d/solve-jobs/${encodeURIComponent(jobId)}/cancel`, {method: "POST"});
  solveJobs = data["队列"] || solveJobs;
  solveJobAudit = data["审计"] || solveJobAudit;
  renderSolveJobs();
  await loadAssetLedger();
  const operation = data["操作"] || {};
  status(operation["说明"] || `已提交取消请求 ${jobId}。`, operation["通过"] === false ? "warning" : "success");
}

async function pauseSolveJob(jobId) {
  const data = await requestJson(`/api/workbench3d/solve-jobs/${encodeURIComponent(jobId)}/pause`, {method: "POST"});
  solveJobs = data["队列"] || solveJobs;
  solveJobAudit = data["审计"] || solveJobAudit;
  renderSolveJobs();
  await loadAssetLedger();
  const operation = data["操作"] || {};
  status(operation["说明"] || `已暂停后台任务 ${jobId}。`, operation["通过"] === false ? "warning" : "success");
}

async function resumeSolveJob(jobId) {
  const data = await requestJson(`/api/workbench3d/solve-jobs/${encodeURIComponent(jobId)}/resume`, {method: "POST"});
  solveJobs = data["队列"] || solveJobs;
  solveJobAudit = data["审计"] || solveJobAudit;
  renderSolveJobs();
  await loadAssetLedger();
  const operation = data["操作"] || {};
  status(operation["说明"] || `已恢复后台任务 ${jobId}。`, operation["通过"] === false ? "warning" : "success");
  if (operation["通过"] !== false) {
    window.setTimeout(() => loadSolveJobs().catch((error) => status(error.message, "danger")), 900);
    window.setTimeout(() => loadResultArchive().catch((error) => status(error.message, "danger")), 1200);
  }
}

async function reviewSolveResult(resultId) {
  solveData = await requestJson(`/api/workbench3d/results/${encodeURIComponent(resultId)}`);
  renderSolveResult();
  renderResultOverlay();
  status(`已复查求解结果 ${resultId}，图层已回写到三维视口。`, "success");
}

async function exportSolveResult(resultId) {
  const result = await requestJson(`/api/workbench3d/results/${encodeURIComponent(resultId)}`);
  const blob = new Blob([JSON.stringify(result, null, 2)], {type: "application/json;charset=utf-8"});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `HPM-DT_${resultId}_${result.scene_hash || "scene"}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

async function onResultArchiveClick(event) {
  const button = event.target.closest("button[data-result-action]");
  if (!button) return;
  const resultId = button.dataset.resultId;
  if (!resultId) return;
  try {
    if (button.dataset.resultAction === "review") await reviewSolveResult(resultId);
    if (button.dataset.resultAction === "export") await exportSolveResult(resultId);
  } catch (error) {
    status(error.message, "danger");
  }
}

async function onSolveJobClick(event) {
  const button = event.target.closest("button[data-job-action]");
  if (!button) return;
  try {
    if (button.dataset.jobAction === "background") await submitBackgroundSolveJob();
    if (button.dataset.jobAction === "audit") await auditSolveJobs();
    if (button.dataset.jobAction === "inspect") await inspectSolveJob(button.dataset.jobId);
    if (button.dataset.jobAction === "review" && button.dataset.resultId) await reviewSolveResult(button.dataset.resultId);
    if (button.dataset.jobAction === "retry") await retrySolveJob(button.dataset.jobId);
    if (button.dataset.jobAction === "pause") await pauseSolveJob(button.dataset.jobId);
    if (button.dataset.jobAction === "resume") await resumeSolveJob(button.dataset.jobId);
    if (button.dataset.jobAction === "cancel") await cancelSolveJob(button.dataset.jobId);
  } catch (error) {
    status(error.message, "danger");
  }
}

function snapshotDiffSummary() {
  if (!snapshotDiff) return "";
  const summary = snapshotDiff["摘要"] || {};
  const objectRows = (snapshotDiff["对象差异"] || []).slice(0, 4).map((item) => {
    const changes = (item["变更"] || []).slice(0, 3).map((change) => `${change["字段"]}: ${formatMetric(change["左"])} -> ${formatMetric(change["右"])}`).join("；");
    return `<small>${item.id} · ${item["名称"] || "--"} · ${changes}</small>`;
  }).join("");
  const materialRows = (snapshotDiff["材料差异"] || []).slice(0, 3).map((item) => {
    const changes = (item["变更"] || []).slice(0, 2).map((change) => `${change["字段"]}: ${formatMetric(change["左"])} -> ${formatMetric(change["右"])}`).join("；");
    return `<small>${item.id} · ${item["名称"] || "--"} · ${changes}</small>`;
  }).join("");
  return `
    <div class="workbench3d-snapshot-diff" data-testid="workbench3d-snapshot-diff">
      <strong>${snapshotDiff["左快照"]?.id || "--"} -> ${snapshotDiff["右快照"]?.id || "--"}</strong>
      <small>对象差异 ${summary["对象差异数"] ?? 0} · 材料差异 ${summary["材料差异数"] ?? 0} · 字段变更 ${summary["字段变更数"] ?? 0}</small>
      ${objectRows}${materialRows}
    </div>`;
}

function renderSnapshotArchive() {
  const panel = $("三维工程快照");
  if (!panel) return;
  if (!snapshotArchive.length) {
    panel.textContent = "尚无三维工程快照。保存快照后会生成可恢复 YAML、场景 JSON 和索引。";
    return;
  }
  const rows = [...snapshotArchive].slice(-5).reverse();
  panel.innerHTML = `
    ${snapshotDiffSummary()}
    <div class="workbench3d-result-archive-list">
      ${rows.map((item) => {
        const index = snapshotArchive.findIndex((record) => record.id === item.id);
        const previous = index > 0 ? snapshotArchive[index - 1] : null;
        return `
          <div class="workbench3d-result-record">
            <div>
              <strong>${item.id}</strong>
              <small>${item["标签"] || "--"} · ${item["创建时间"] || "--"}</small>
            </div>
            <div>
              <small>scene_hash ${item.scene_hash || "--"} · 对象 ${item["对象总数"] ?? "--"} · 启用 ${item["启用对象数"] ?? "--"}</small>
              <small>${item["工程路径"] ? "YAML已落盘" : "内存快照"} · ${item["场景路径"] ? "场景JSON已落盘" : "场景未落盘"}</small>
            </div>
            <div class="workbench3d-result-record-actions">
              <button type="button" data-snapshot-action="restore" data-snapshot-id="${escapeAttr(item.id)}">恢复</button>
              ${previous ? `<button type="button" data-snapshot-action="diff" data-left-id="${escapeAttr(previous.id)}" data-right-id="${escapeAttr(item.id)}">对比</button>` : ""}
            </div>
          </div>`;
      }).join("")}
    </div>`;
}

async function loadSnapshotArchive() {
  const data = await requestJson("/api/workbench3d/snapshots");
  snapshotArchive = data["快照"] || [];
  if (sceneData && data["历史"]) {
    sceneData["历史"] = data["历史"];
    updateHistoryControls();
  }
  renderSnapshotArchive();
}

async function restoreSnapshotRecord(snapshotId) {
  sceneData = await requestJson(`/api/workbench3d/snapshots/${encodeURIComponent(snapshotId)}/restore`, {method: "POST"});
  selectedId = sceneData["对象"].length ? sceneData["对象"][0].id : null;
  selectedMaterialId = materialLibrary().length ? materialLibrary()[0].id : null;
  solveData = null;
  rebuildScene();
  renderSolveResult();
  await loadSnapshotArchive();
  await loadAssetLedger();
  status(`已恢复工程快照 ${snapshotId}。`, "success");
}

async function diffSnapshotRecords(leftId, rightId) {
  snapshotDiff = await requestJson(`/api/workbench3d/snapshots/${encodeURIComponent(leftId)}/diff/${encodeURIComponent(rightId)}`);
  renderSnapshotArchive();
  const summary = snapshotDiff["摘要"] || {};
  status(`已对比工程快照 ${leftId} -> ${rightId}：字段变更 ${summary["字段变更数"] ?? 0}。`, "success");
}

async function onSnapshotArchiveClick(event) {
  const button = event.target.closest("button[data-snapshot-action]");
  if (!button) return;
  try {
    if (button.dataset.snapshotAction === "restore") await restoreSnapshotRecord(button.dataset.snapshotId);
    if (button.dataset.snapshotAction === "diff") await diffSnapshotRecords(button.dataset.leftId, button.dataset.rightId);
  } catch (error) {
    status(error.message, "danger");
  }
}

function assetClass(item) {
  if (item["类型"] === "求解任务") return "job";
  if (item["类型"] === "求解结果") return "result";
  if (item["类型"] === "工程快照") return "snapshot";
  if (item["类型"] === "导入标定桥接") return "imported";
  if (item["类型"] === "材料代理审计") return "material";
  return "";
}

function assetLedgerUrl(path, limit = 12) {
  const params = new URLSearchParams();
  if (assetLedgerFilter.type && assetLedgerFilter.type !== "全部") params.set("asset_type", assetLedgerFilter.type);
  if (assetLedgerFilter.query) params.set("q", assetLedgerFilter.query);
  if (limit) params.set("limit", String(limit));
  const suffix = params.toString();
  return suffix ? `${path}?${suffix}` : path;
}

function assetTypeOptions() {
  return ["全部", "工程快照", "求解任务", "求解结果", "导入标定桥接", "材料代理审计"].map((item) => {
    const selected = assetLedgerFilter.type === item ? "selected" : "";
    return `<option value="${escapeAttr(item)}" ${selected}>${escapeAttr(item)}</option>`;
  }).join("");
}

function assetCountsSummary() {
  const counts = assetLedgerSummary["类型计数"] || {};
  const dbRows = assetDatabaseAudit["行数"] || {};
  return [
    `总计 ${assetLedgerSummary["总数"] ?? 0}`,
    `快照 ${counts["工程快照"] || 0}`,
    `任务 ${counts["求解任务"] || 0}`,
    `结果 ${counts["求解结果"] || 0}`,
    `材料审计 ${counts["材料代理审计"] || 0}`,
    `匹配 ${assetLedgerAudit["匹配资产"] ?? assetLedger.length}`,
    `事件 ${dbRows.workbench3d_solve_job_events ?? assetDatabaseAudit["任务事件数"] ?? "--"}`,
    `库表 ${assetDatabaseRecords["表数量"] ?? "--"}`,
    `谱系 ${assetLineage["摘要"]?.["边数"] ?? "--"}`,
    `复现 ${assetReproducibilityAudit["摘要"]?.["可复查结果数"] ?? "--"}`,
    `标定 ${assetAbsoluteCalibration["校准结果"]?.["相对RMSE_percent"] ?? "--"}%`,
    `导入 ${assetImportedCalibration["摘要"]?.["样本数"] ?? "--"}点`,
    `材料 ${assetMaterialAudit["材料数量"] ?? "--"}`,
  ];
}

function assetFilterControls() {
  return `
    <div class="workbench3d-asset-toolbar" data-testid="workbench3d-asset-filters">
      <select data-asset-filter="type" aria-label="资产类型">${assetTypeOptions()}</select>
      <input type="search" data-asset-filter="query" value="${escapeAttr(assetLedgerFilter.query || "")}" placeholder="资产、哈希、标签或路径">
      <button type="button" data-asset-action="filter">筛选</button>
      <button type="button" data-asset-action="clear">清空</button>
      <button type="button" data-asset-action="audit">审计</button>
      <button type="button" data-asset-action="database">数据库</button>
      <button type="button" data-asset-action="records">库表</button>
      <button type="button" data-asset-action="lineage">追溯</button>
      <button type="button" data-asset-action="reproducibility">复现</button>
      <button type="button" data-asset-action="calibration">标定</button>
      <button type="button" data-asset-action="imported-calibration">导入</button>
      <button type="button" data-asset-action="materials">材料</button>
      <button type="button" data-asset-action="naming">命名</button>
    </div>
    <div class="workbench3d-asset-summary" data-testid="workbench3d-asset-summary">
      ${assetCountsSummary().map((item) => `<span>${escapeAttr(item)}</span>`).join("")}
      <span>${escapeAttr(assetLedgerAudit["结论"] ? `审计 ${assetLedgerAudit["结论"]}` : "审计 --")}</span>
      <span>${escapeAttr(assetDatabaseAudit["结论"] ? `数据库 ${assetDatabaseAudit["结论"]}` : "数据库 --")}</span>
      <span>${escapeAttr(assetNamingAudit["结论"] ? `命名 ${assetNamingAudit["结论"]}` : "命名 --")}</span>
      <span>${escapeAttr(assetReproducibilityAudit["结论"] ? `复现 ${assetReproducibilityAudit["结论"]}` : "复现 --")}</span>
      <span>${escapeAttr(assetAbsoluteCalibration["结论"] ? `标定 ${assetAbsoluteCalibration["结论"]}` : "标定 --")}</span>
      <span>${escapeAttr(assetImportedCalibration["结论"] ? `导入 ${assetImportedCalibration["结论"]}` : "导入 --")}</span>
      <span>${escapeAttr(assetMaterialAudit["结论"] ? `材料 ${assetMaterialAudit["结论"]}` : "材料 --")}</span>
    </div>`;
}

function assetDatabaseRecordBrowser() {
  if (!assetDatabaseRecords || !assetDatabaseRecords["表数量"]) return "";
  const rowCounts = assetDatabaseRecords["行数"] || {};
  const schemas = assetDatabaseRecords["结构"] || {};
  const records = assetDatabaseRecords["记录"] || {};
  const tableNames = (assetDatabaseRecords["表"] || Object.keys(rowCounts)).filter(Boolean);
  const priority = [
    "workbench3d_solve_jobs",
    "workbench3d_results",
    "workbench3d_snapshots",
    "workbench3d_database_manifest",
  ];
  const previewTables = [
    ...priority.filter((name) => tableNames.includes(name)),
    ...tableNames.filter((name) => !priority.includes(name)),
  ].slice(0, 4);
  return `
    <div class="workbench3d-db-records" data-testid="workbench3d-database-records">
      <div class="workbench3d-db-records-head">
        <strong>库表浏览</strong>
        <span>${escapeAttr(assetDatabaseRecords["表数量"])} 张表 · 审计 ${escapeAttr(assetDatabaseRecords["审计"]?.["结论"] || "--")}</span>
      </div>
      <div class="workbench3d-db-records-grid">
        ${previewTables.map((tableName) => {
          const columns = (schemas[tableName] || []).slice(0, 6).map((item) => item["列"] || "--").join(", ");
          const samples = (records[tableName] || []).slice(0, 2).map((row) => {
            const cells = Object.entries(row)
              .filter(([key]) => key !== "raw_json")
              .slice(0, 4)
              .map(([key, value]) => `${key}: ${value ?? "--"}`)
              .join(" · ");
            return `<small>${escapeAttr(cells || "无样例行")}</small>`;
          }).join("");
          return `
            <div class="workbench3d-db-record">
              <strong>${escapeAttr(tableName)}</strong>
              <span>${escapeAttr(rowCounts[tableName] ?? 0)} 行</span>
              <small>字段 ${escapeAttr(columns || "--")}</small>
              ${samples || "<small>无样例行</small>"}
            </div>`;
        }).join("")}
      </div>
    </div>`;
}

function assetLineageBrowser() {
  if (!assetLineage || !assetLineage["摘要"]) return "";
  const summary = assetLineage["摘要"] || {};
  const edges = (assetLineage["边"] || []).slice(0, 8);
  const checks = (assetLineage["验收清单"] || []).slice(0, 5);
  return `
    <div class="workbench3d-lineage" data-testid="workbench3d-asset-lineage">
      <div class="workbench3d-lineage-head">
        <strong>资产谱系</strong>
        <span>${escapeAttr(summary["节点数"] ?? 0)} 节点 · ${escapeAttr(summary["边数"] ?? 0)} 边 · 审计 ${escapeAttr(assetLineage["结论"] || "--")}</span>
      </div>
      <div class="workbench3d-lineage-checks">
        ${checks.map((item) => `<span class="${item["通过"] === false ? "warn" : "ok"}">${escapeAttr(item["项目"] || "--")}</span>`).join("")}
      </div>
      <div class="workbench3d-lineage-list">
        ${edges.map((edge) => `
          <div class="workbench3d-lineage-edge">
            <strong>${escapeAttr(edge.source || "--")} → ${escapeAttr(edge.target || "--")}</strong>
            <small>${escapeAttr(edge["关系"] || "--")} · scene_hash ${escapeAttr(edge.scene_hash || "--")} · field_hash ${escapeAttr(edge.field_hash || "--")}</small>
            <small>${escapeAttr(edge["证据"] || "--")}</small>
          </div>`).join("") || "<div class=\"workbench3d-lineage-edge\"><small>暂无可显示谱系边。</small></div>"}
      </div>
    </div>`;
}

function assetReproducibilityBrowser() {
  if (!assetReproducibilityAudit || !assetReproducibilityAudit["摘要"]) return "";
  const summary = assetReproducibilityAudit["摘要"] || {};
  const checks = (assetReproducibilityAudit["验收清单"] || []).slice(0, 5);
  const records = (assetReproducibilityAudit["结果复现记录"] || []).slice(0, 6);
  return `
    <div class="workbench3d-lineage workbench3d-reproducibility" data-testid="workbench3d-asset-reproducibility">
      <div class="workbench3d-lineage-head">
        <strong>可复现实验审计</strong>
        <span>${escapeAttr(summary["结果数"] ?? 0)} 结果 · 可复查 ${escapeAttr(summary["可复查结果数"] ?? 0)} · 审计 ${escapeAttr(assetReproducibilityAudit["结论"] || "--")}</span>
      </div>
      <div class="workbench3d-lineage-checks">
        ${checks.map((item) => `<span class="${item["通过"] === false ? "warn" : "ok"}">${escapeAttr(item["项目"] || "--")}</span>`).join("")}
      </div>
      <div class="workbench3d-lineage-list">
        ${records.map((record) => `
          <div class="workbench3d-lineage-edge">
            <strong>${escapeAttr(record.result_id || "--")} · ${escapeAttr(record["复现等级"] || "--")}</strong>
            <small>${escapeAttr(record["来源"] || "--")} · JOB ${escapeAttr(record["任务id"] || "--")} · scene_hash ${escapeAttr(record.scene_hash || "--")}</small>
            <small>${escapeAttr(record["摘要"] || "--")}</small>
          </div>`).join("") || "<div class=\"workbench3d-lineage-edge\"><small>暂无可复查结果。</small></div>"}
      </div>
    </div>`;
}

function assetCalibrationBrowser() {
  const data = assetAbsoluteCalibration && assetAbsoluteCalibration["版本"] ? assetAbsoluteCalibration : absoluteCalibration;
  if (!data || !data["校准结果"]) return "";
  const result = data["校准结果"] || {};
  const power = data["功率元数据"] || {};
  const checks = (data["验收清单"] || []).slice(0, 5);
  return `
    <div class="workbench3d-lineage workbench3d-asset-calibration" data-testid="workbench3d-asset-calibration">
      <div class="workbench3d-lineage-head">
        <strong>绝对量纲标定</strong>
        <span>总功率 ${escapeAttr(power["总输入功率_w"] ?? "--")} W · RMSE ${escapeAttr(result["残差RMSE_v_per_m"] ?? "--")} V/m · ${escapeAttr(data["结论"] || "--")}</span>
      </div>
      <div class="workbench3d-lineage-checks">
        ${checks.map((item) => `<span class="${item["通过"] === false ? "warn" : "ok"}">${escapeAttr(item["项目"] || "--")}</span>`).join("")}
      </div>
      <div class="workbench3d-calibration-summary">
        ${calibrationSummaryChips(data).map((item) => `<span>${escapeAttr(item)}</span>`).join("")}
      </div>
      <small>${escapeAttr(data["安全边界"] || "")}</small>
    </div>`;
}

function assetImportedCalibrationBrowser() {
  const data = assetImportedCalibration && assetImportedCalibration["版本"] ? assetImportedCalibration : sceneData?.["导入数据标定桥接"] || {};
  if (!data || !data["摘要"]) return "";
  const summary = data["摘要"] || {};
  const checks = (data["验收清单"] || []).slice(0, 5);
  const risks = (data["外部数据V&V审计"]?.["风险信号"] || []).slice(0, 4);
  const points = (data["模型误差对比"]?.["逐点残差"] || []).slice(0, 4);
  return `
    <div class="workbench3d-lineage workbench3d-imported-calibration" data-testid="workbench3d-imported-calibration">
      <div class="workbench3d-lineage-head">
        <strong>导入数据标定桥接</strong>
        <span>${escapeAttr(summary["样本数"] ?? "--")} 样本 · RMSE ${escapeAttr(summary["标定后相对RMSE/%"] ?? "--")}% · ${escapeAttr(data["结论"] || "--")}</span>
      </div>
      <div class="workbench3d-calibration-summary">
        <span>源 ${escapeAttr(summary["导入源名称"] || "--")}</span>
        <span>坐标 ${escapeAttr(summary["坐标来源单位"] || "--")} -> ${escapeAttr(summary["目标坐标"] || "--")}</span>
        <span>2σ ${escapeAttr(summary["2sigma覆盖率/%"] ?? "--")}%</span>
        <span>预评分 ${escapeAttr(summary["预评分"] ?? "--")} ${escapeAttr(summary["预评分等级"] || "")}</span>
        <span>${summary["可纳入正式可信度评分"] ? "已纳入正式评分" : "未纳入正式评分"}</span>
      </div>
      <div class="workbench3d-lineage-checks">
        ${checks.map((item) => `<span class="${item["通过"] === false ? "warn" : "ok"}">${escapeAttr(item["项目"] || "--")}</span>`).join("")}
      </div>
      <div class="workbench3d-lineage-list">
        ${points.map((item) => `
          <div class="workbench3d-lineage-edge">
            <strong>点 ${escapeAttr(item["序号"] || "--")} · 残差 ${escapeAttr(item["复场残差"] ?? "--")}</strong>
            <small>x ${escapeAttr(item.x_lambda ?? "--")} · y ${escapeAttr(item.y_lambda ?? "--")} · z ${escapeAttr(item.z_lambda ?? "--")} · 归一化残差 ${escapeAttr(item["归一化残差"] ?? "--")}</small>
          </div>`).join("") || risks.map((item) => `
          <div class="workbench3d-lineage-edge"><small>${escapeAttr(item)}</small></div>`).join("") || "<div class=\"workbench3d-lineage-edge\"><small>暂无导入残差预览。</small></div>"}
      </div>
      <small>${escapeAttr(data["安全边界"] || "")}</small>
    </div>`;
}

function readAssetFilterControls() {
  const panel = $("三维资产台账");
  const typeInput = panel?.querySelector("[data-asset-filter='type']");
  const queryInput = panel?.querySelector("[data-asset-filter='query']");
  assetLedgerFilter = {
    type: typeInput?.value || "全部",
    query: (queryInput?.value || "").trim(),
  };
}

function renderAssetLedger() {
  const panel = $("三维资产台账");
  if (!panel) return;
  if (!assetLedger.length) {
    panel.innerHTML = `
      ${assetFilterControls()}
      ${assetDatabaseRecordBrowser()}
      ${assetLineageBrowser()}
      ${assetReproducibilityBrowser()}
      ${assetCalibrationBrowser()}
      ${assetImportedCalibrationBrowser()}
      <div class="workbench3d-asset-empty">尚无匹配工程资产。生成任务、结果或快照后会自动汇总。</div>`;
    return;
  }
  const rows = [...assetLedger].slice(0, 8);
  panel.innerHTML = `
    ${assetFilterControls()}
    ${assetDatabaseRecordBrowser()}
    ${assetLineageBrowser()}
    ${assetReproducibilityBrowser()}
    ${assetCalibrationBrowser()}
    ${assetImportedCalibrationBrowser()}
    <div class="workbench3d-asset-list">
      ${rows.map((item) => `
        <div class="workbench3d-asset-record ${assetClass(item)}">
          <div>
            <strong>${escapeAttr(item["资产id"] || "--")}</strong>
            <small>${escapeAttr(item["类型"] || "--")} · ${escapeAttr(item["状态"] || "--")}</small>
          </div>
          <div>
            <small>${escapeAttr(item["标签"] || "--")} · ${escapeAttr(item["创建时间"] || "--")}</small>
            <small>scene_hash ${escapeAttr(item.scene_hash || "--")} · field_hash ${escapeAttr(item.field_hash || "--")}</small>
            <small>${escapeAttr(item["摘要"] || "--")}</small>
          </div>
          <div class="workbench3d-asset-actions">
            <button type="button" data-asset-action="open" data-asset-id="${escapeAttr(item["资产id"] || "")}" data-asset-type="${escapeAttr(item["类型"] || "")}" data-job-id="${escapeAttr(item.job_id || "")}" data-result-id="${escapeAttr(item.result_id || "")}">打开</button>
          </div>
        </div>`).join("")}
    </div>`;
}

async function loadAssetLedger() {
  const data = await requestJson(assetLedgerUrl("/api/workbench3d/assets"));
  assetLedger = data["资产"] || [];
  assetLedgerSummary = data["摘要"] || {};
  assetLedgerAudit = data["审计"] || {};
  assetDatabaseAudit = data["数据库审计"] || assetDatabaseAudit;
  assetDatabaseRecords = data["数据库记录"] || assetDatabaseRecords;
  assetLineage = data["资产谱系"] || assetLineage;
  assetNamingAudit = data["命名审计"] || assetNamingAudit;
  assetReproducibilityAudit = data["复现审计"] || assetReproducibilityAudit;
  assetAbsoluteCalibration = data["绝对量纲标定"] || assetAbsoluteCalibration;
  assetImportedCalibration = data["导入数据标定桥接"] || assetImportedCalibration;
  assetMaterialAudit = data["材料代理审计"] || assetMaterialAudit;
  absoluteCalibration = assetAbsoluteCalibration && assetAbsoluteCalibration["版本"] ? assetAbsoluteCalibration : absoluteCalibration;
  if (sceneData && absoluteCalibration && absoluteCalibration["版本"]) sceneData["绝对量纲标定"] = absoluteCalibration;
  if (sceneData && assetImportedCalibration && assetImportedCalibration["版本"]) sceneData["导入数据标定桥接"] = assetImportedCalibration;
  if (sceneData && assetMaterialAudit && assetMaterialAudit["版本"]) sceneData["材料代理审计"] = assetMaterialAudit;
  if (sceneData && data["历史"]) {
    sceneData["历史"] = data["历史"];
    updateHistoryControls();
  }
  renderAssetLedger();
}

async function openAssetRecord(button) {
  const assetId = button.dataset.assetId;
  const assetType = button.dataset.assetType;
  if (assetType === "求解任务" && button.dataset.jobId) {
    await inspectSolveJob(button.dataset.jobId);
  } else if (assetType === "求解结果" && button.dataset.resultId) {
    await reviewSolveResult(button.dataset.resultId);
  } else if (assetType === "工程快照" && assetId) {
    await restoreSnapshotRecord(assetId);
  } else if (assetId) {
    await requestJson(`/api/workbench3d/assets/${encodeURIComponent(assetId)}`);
  }
  status(`已打开工程资产 ${assetId || "--"}。`, "success");
}

async function auditAssetLedger() {
  readAssetFilterControls();
  const data = await requestJson(assetLedgerUrl("/api/workbench3d/assets/audit", 0));
  assetLedgerAudit = data["审计"] || {};
  renderAssetLedger();
  status(`资产台账审计${assetLedgerAudit["结论"] || "--"}：匹配 ${assetLedgerAudit["匹配资产"] ?? assetLedger.length} 条。`, assetLedgerAudit["通过"] === false ? "warning" : "success");
}

async function auditAssetDatabase() {
  const data = await requestJson("/api/workbench3d/assets/database");
  assetDatabaseAudit = data["数据库审计"] || {};
  renderAssetLedger();
  const rows = assetDatabaseAudit["行数"] || {};
  status(
    `资产数据库${assetDatabaseAudit["结论"] || "--"}：资产 ${rows.workbench3d_assets ?? "--"} 行，任务事件 ${rows.workbench3d_solve_job_events ?? "--"} 行。`,
    assetDatabaseAudit["通过"] === false ? "warning" : "success",
  );
}

async function browseAssetDatabaseRecords() {
  const data = await requestJson("/api/workbench3d/assets/database/records?limit=8");
  assetDatabaseRecords = data || {};
  assetDatabaseAudit = data["审计"] || assetDatabaseAudit;
  renderAssetLedger();
  const rows = assetDatabaseRecords["行数"] || {};
  status(
    `资产库表已读取：任务 ${rows.workbench3d_solve_jobs ?? "--"} 行，结果 ${rows.workbench3d_results ?? "--"} 行，快照 ${rows.workbench3d_snapshots ?? "--"} 行。`,
    assetDatabaseRecords["审计"]?.["通过"] === false ? "warning" : "success",
  );
}

async function browseAssetLineage() {
  const data = await requestJson("/api/workbench3d/assets/lineage");
  assetLineage = data || {};
  renderAssetLedger();
  const summary = assetLineage["摘要"] || {};
  status(
    `资产谱系已生成：节点 ${summary["节点数"] ?? "--"} 个，边 ${summary["边数"] ?? "--"} 条，任务结果边 ${summary["任务结果边"] ?? "--"} 条。`,
    assetLineage["通过"] === false ? "warning" : "success",
  );
}

async function browseAssetReproducibility() {
  const data = await requestJson("/api/workbench3d/assets/reproducibility");
  assetReproducibilityAudit = data || {};
  renderAssetLedger();
  const summary = assetReproducibilityAudit["摘要"] || {};
  status(
    `复现审计已生成：结果 ${summary["结果数"] ?? "--"} 个，可复查 ${summary["可复查结果数"] ?? "--"} 个。`,
    assetReproducibilityAudit["通过"] === false ? "warning" : "success",
  );
}

async function browseAssetCalibration() {
  const data = await loadAbsoluteCalibration();
  assetAbsoluteCalibration = data || {};
  renderAssetLedger();
  const result = assetAbsoluteCalibration["校准结果"] || {};
  status(
    `绝对量纲标定已生成：RMSE ${formatMetric(result["残差RMSE_v_per_m"], " V/m", 4)}；仅表示实测点覆盖区间。`,
    assetAbsoluteCalibration["通过"] === false ? "warning" : "success",
  );
}

async function browseAssetImportedCalibration() {
  const data = await requestJson("/api/workbench3d/assets/imported-calibration");
  assetImportedCalibration = data || {};
  if (sceneData) sceneData["导入数据标定桥接"] = assetImportedCalibration;
  renderAssetLedger();
  renderProperties();
  const summary = assetImportedCalibration["摘要"] || {};
  status(
    `导入数据标定桥接：样本 ${summary["样本数"] ?? "--"} 个，相对RMSE ${summary["标定后相对RMSE/%"] ?? "--"}%，${summary["可纳入正式可信度评分"] ? "已纳入正式评分" : "未纳入正式评分"}。`,
    assetImportedCalibration["通过"] === false ? "warning" : "success",
  );
}

async function auditMaterials() {
  const data = await requestJson("/api/workbench3d/materials/audit");
  assetMaterialAudit = data["材料代理审计"] || {};
  if (sceneData && assetMaterialAudit["版本"]) sceneData["材料代理审计"] = assetMaterialAudit;
  await loadAssetLedger();
  status(
    `材料代理审计${assetMaterialAudit["结论"] || "--"}：材料 ${assetMaterialAudit["材料数量"] ?? "--"} 个，引用 ${assetMaterialAudit["引用关系数量"] ?? "--"} 条。`,
    assetMaterialAudit["通过"] === false ? "warning" : "success",
  );
}

async function auditAssetNaming() {
  const data = await requestJson("/api/workbench3d/assets/naming");
  assetNamingAudit = data["命名审计"] || {};
  renderAssetLedger();
  const stats = assetNamingAudit["统计"] || {};
  status(
    `资产命名${assetNamingAudit["结论"] || "--"}：路径检查 ${stats["路径检查数"] ?? "--"} 条，问题 ${stats["问题数"] ?? "--"} 条。`,
    assetNamingAudit["通过"] === false ? "warning" : "success",
  );
}

async function onAssetLedgerClick(event) {
  const button = event.target.closest("button[data-asset-action]");
  if (!button) return;
  try {
    if (button.dataset.assetAction === "open") await openAssetRecord(button);
    if (button.dataset.assetAction === "filter") {
      readAssetFilterControls();
      await loadAssetLedger();
      status(`资产台账筛选完成：${assetLedger.length} 条返回。`, "success");
    }
    if (button.dataset.assetAction === "clear") {
      assetLedgerFilter = {type: "全部", query: ""};
      await loadAssetLedger();
      status("资产台账筛选已清空。", "success");
    }
    if (button.dataset.assetAction === "audit") await auditAssetLedger();
    if (button.dataset.assetAction === "database") await auditAssetDatabase();
    if (button.dataset.assetAction === "records") await browseAssetDatabaseRecords();
    if (button.dataset.assetAction === "lineage") await browseAssetLineage();
    if (button.dataset.assetAction === "reproducibility") await browseAssetReproducibility();
    if (button.dataset.assetAction === "calibration") await browseAssetCalibration();
    if (button.dataset.assetAction === "imported-calibration") await browseAssetImportedCalibration();
    if (button.dataset.assetAction === "materials") await auditMaterials();
    if (button.dataset.assetAction === "naming") await auditAssetNaming();
  } catch (error) {
    status(error.message, "danger");
  }
}

async function onAssetLedgerKeydown(event) {
  if (event.key !== "Enter") return;
  if (!event.target.closest("[data-asset-filter]")) return;
  event.preventDefault();
  try {
    readAssetFilterControls();
    await loadAssetLedger();
    status(`资产台账筛选完成：${assetLedger.length} 条返回。`, "success");
  } catch (error) {
    status(error.message, "danger");
  }
}

function onObjectMetricClick(event) {
  const button = event.target.closest("button[data-metric-object-id]");
  if (!button) return;
  selectObject(button.dataset.metricObjectId);
}

function onProfileAxisClick(event) {
  const button = event.target.closest("button[data-profile-axis]");
  if (!button) return;
  const nextAxis = button.dataset.profileAxis === "y" ? "y" : "x";
  if (profileAxis === nextAxis) return;
  profileAxis = nextAxis;
  renderSolveResult();
}

function disposeMaterial(material) {
  if (!material) return;
  if (material.map) material.map.dispose();
  material.dispose();
}

function disposeNode(node) {
  if (node.geometry) node.geometry.dispose();
  if (node.material) {
    if (Array.isArray(node.material)) node.material.forEach(disposeMaterial);
    else disposeMaterial(node.material);
  }
}

function heatColor(value, minValue, maxValue) {
  const clamped = Math.max(minValue, Math.min(maxValue, Number(value)));
  const t = (clamped - minValue) / Math.max(maxValue - minValue, 1e-9);
  const stops = [
    [0.00, [22, 35, 74]],
    [0.28, [31, 117, 164]],
    [0.52, [42, 176, 127]],
    [0.76, [236, 196, 77]],
    [1.00, [204, 61, 74]],
  ];
  for (let i = 1; i < stops.length; i += 1) {
    if (t <= stops[i][0]) {
      const [leftT, left] = stops[i - 1];
      const [rightT, right] = stops[i];
      const u = (t - leftT) / Math.max(rightT - leftT, 1e-9);
      return left.map((channel, index) => Math.round(channel + (right[index] - channel) * u));
    }
  }
  return stops[stops.length - 1][1];
}

function makeResultTexture(layer) {
  const values = layer && layer.values_db;
  if (!Array.isArray(values) || !values.length || !Array.isArray(values[0])) return null;
  const height = values.length;
  const width = values[0].length;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  const image = ctx.createImageData(width, height);
  const minValue = Number(layer["色标"]?.["最小值"] ?? -30);
  const maxValue = Number(layer["色标"]?.["最大值"] ?? 4);
  for (let y = 0; y < height; y += 1) {
    const source = values[height - 1 - y] || [];
    for (let x = 0; x < width; x += 1) {
      const offset = 4 * (y * width + x);
      const [r, g, b] = heatColor(source[x], minValue, maxValue);
      image.data[offset] = r;
      image.data[offset + 1] = g;
      image.data[offset + 2] = b;
      image.data[offset + 3] = 218;
    }
  }
  ctx.putImageData(image, 0, 0);
  const texture = new THREE.CanvasTexture(canvas);
  texture.magFilter = THREE.NearestFilter;
  texture.minFilter = THREE.LinearFilter;
  texture.needsUpdate = true;
  return texture;
}

function clearResultOverlay() {
  if (resultOverlay && root) {
    resultOverlay.traverse(disposeNode);
    root.remove(resultOverlay);
  }
  resultOverlay = null;
}

function createResultOverlay() {
  const layer = solveData && solveData["结果图层"];
  if (!layer || layer["类型"] !== "observation_field_db") return null;
  const texture = makeResultTexture(layer);
  if (!texture) return null;
  const bounds = layer.bounds || {};
  const xBounds = bounds.x || [-1, 1];
  const yBounds = bounds.y || [-1, 1];
  const width = Math.max(Number(xBounds[1]) - Number(xBounds[0]), 0.01);
  const height = Math.max(Number(yBounds[1]) - Number(yBounds[0]), 0.01);
  const material = new THREE.MeshBasicMaterial({
    map: texture,
    transparent: true,
    opacity: 0.82,
    side: THREE.DoubleSide,
    depthWrite: false,
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(width, height), material);
  mesh.position.set((Number(xBounds[0]) + Number(xBounds[1])) / 2, (Number(yBounds[0]) + Number(yBounds[1])) / 2, Number(layer.z_lambda || 0) + 0.12);
  mesh.renderOrder = 4;
  const group = new THREE.Group();
  group.name = "workbench3d-result-layer";
  group.add(mesh);
  const outline = makeLine([
    [Number(xBounds[0]), Number(yBounds[0]), mesh.position.z + 0.02],
    [Number(xBounds[1]), Number(yBounds[0]), mesh.position.z + 0.02],
    [Number(xBounds[1]), Number(yBounds[1]), mesh.position.z + 0.02],
    [Number(xBounds[0]), Number(yBounds[1]), mesh.position.z + 0.02],
  ], colors.selected);
  outline.renderOrder = 5;
  group.add(outline);
  const metricRows = solveData["对象指标"] || [];
  const objectsById = new Map((sceneData ? sceneData["对象"] || [] : []).map((item) => [item.id, item]));
  metricRows.forEach((row) => {
    const item = objectsById.get(row.object_id);
    if (item) addMetricBadge(group, row, item);
  });
  return group;
}

function renderResultOverlay() {
  if (!root) return;
  clearResultOverlay();
  const overlay = createResultOverlay();
  if (!overlay) return;
  resultOverlay = overlay;
  root.add(resultOverlay);
}

function setMoveMode(enabled) {
  moveMode = Boolean(enabled);
  const button = $("三维移动模式");
  const viewport = $("三维视口");
  if (button) button.classList.toggle("move-mode-active", moveMode);
  if (viewport) viewport.classList.toggle("move-mode", moveMode);
  if (moveMode) status("移动模式已开启：拖动目标区、保护区、孔缝或腔体，松手后自动做后端几何校验。", "info");
  else status("移动模式已关闭：拖动画布旋转视图。", "info");
}

function vec3(values) {
  return new THREE.Vector3(values[0], values[1], values[2]);
}

function makeMaterial(color, opacity = 1, wireframe = false) {
  return new THREE.MeshStandardMaterial({
    color,
    transparent: opacity < 1,
    opacity,
    roughness: 0.62,
    metalness: 0.08,
    side: THREE.DoubleSide,
    wireframe,
  });
}

function makeLine(points, color, dashed = false) {
  const geometry = new THREE.BufferGeometry().setFromPoints(points.map(vec3));
  const material = dashed
    ? new THREE.LineDashedMaterial({color, dashSize: 0.18, gapSize: 0.12})
    : new THREE.LineBasicMaterial({color});
  const line = new THREE.LineLoop(geometry, material);
  if (dashed) line.computeLineDistances();
  return line;
}

function ellipsePoints(center, axes, rotationDeg, zOffset = 0) {
  const points = [];
  const rot = rotationDeg * Math.PI / 180;
  const cosR = Math.cos(rot);
  const sinR = Math.sin(rot);
  for (let i = 0; i < 96; i += 1) {
    const t = i / 96 * Math.PI * 2;
    const x = axes[0] * Math.cos(t);
    const y = axes[1] * Math.sin(t);
    points.push([
      center[0] + x * cosR - y * sinR,
      center[1] + x * sinR + y * cosR,
      center[2] + zOffset,
    ]);
  }
  return points;
}

function circlePoints(center, radius, zOffset = 0) {
  const points = [];
  for (let i = 0; i < 96; i += 1) {
    const t = i / 96 * Math.PI * 2;
    points.push([center[0] + radius * Math.cos(t), center[1] + radius * Math.sin(t), center[2] + zOffset]);
  }
  return points;
}

function addLabel(group, text, position) {
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "rgba(249,250,251,.92)";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#111827";
  ctx.font = "24px Microsoft YaHei, Segoe UI, sans-serif";
  ctx.fillText(text.slice(0, 14), 16, 40);
  const texture = new THREE.CanvasTexture(canvas);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map: texture, transparent: true}));
  sprite.position.copy(position);
  sprite.scale.set(1.55, 0.38, 1);
  group.add(sprite);
}

function addMetricBadge(group, row, item) {
  const center = centerOfObject(item);
  if (!center) return;
  const ok = objectMetricStatus(row) === "通过";
  const canvas = document.createElement("canvas");
  canvas.width = 384;
  canvas.height = 94;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = ok ? "rgba(236,253,245,.94)" : "rgba(255,247,237,.94)";
  ctx.strokeStyle = ok ? "#10b981" : "#f59e0b";
  ctx.lineWidth = 5;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeRect(2, 2, canvas.width - 4, canvas.height - 4);
  ctx.fillStyle = ok ? "#065f46" : "#92400e";
  ctx.font = "700 23px Microsoft YaHei, Segoe UI, sans-serif";
  ctx.fillText(`${objectMetricStatus(row)} · ${String(row.name || row.object_id || "--").slice(0, 12)}`, 18, 34);
  ctx.fillStyle = "#1f2937";
  ctx.font = "19px Microsoft YaHei, Segoe UI, sans-serif";
  ctx.fillText(objectMetricBadgeText(row).slice(0, 28), 18, 68);
  const texture = new THREE.CanvasTexture(canvas);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map: texture, transparent: true, depthTest: false}));
  sprite.position.set(center.x + 0.18, center.y + 0.18, center.z + 0.9);
  sprite.scale.set(2.2, 0.54, 1);
  sprite.renderOrder = 8;
  group.add(sprite);
}

function addEdges(mesh, color = 0xffffff) {
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(mesh.geometry),
    new THREE.LineBasicMaterial({color, transparent: true, opacity: 0.72})
  );
  edges.position.copy(mesh.position);
  edges.rotation.copy(mesh.rotation);
  edges.scale.copy(mesh.scale);
  mesh.parent.add(edges);
  return edges;
}

function renderGrid(bounds, step) {
  const group = new THREE.Group();
  group.name = "grid";
  const [xmin, xmax] = bounds.x;
  const [ymin, ymax] = bounds.y;
  const mat = new THREE.LineBasicMaterial({color: colors.grid, transparent: true, opacity: 0.72});
  for (let x = Math.ceil(xmin / step) * step; x <= xmax + 1e-9; x += step) {
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(x, ymin, 0),
      new THREE.Vector3(x, ymax, 0),
    ]), mat);
    group.add(line);
  }
  for (let y = Math.ceil(ymin / step) * step; y <= ymax + 1e-9; y += step) {
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(xmin, y, 0),
      new THREE.Vector3(xmax, y, 0),
    ]), mat);
    group.add(line);
  }
  return group;
}

function renderArray(item) {
  const g = item["几何"];
  const group = new THREE.Group();
  const panel = new THREE.Mesh(
    new THREE.BoxGeometry(Math.max(g.size[0], 0.05), Math.max(g.size[1], 0.05), 0.08),
    makeMaterial(colors.array, 0.14)
  );
  panel.position.set(0, 0, 0.02);
  group.add(panel);
  addEdges(panel, colors.array);
  const dotGeometry = new THREE.SphereGeometry(0.055, 12, 8);
  const dotMaterial = makeMaterial(colors.array, 0.95);
  const dots = new THREE.InstancedMesh(dotGeometry, dotMaterial, g.nx * g.ny);
  const matrix = new THREE.Matrix4();
  let index = 0;
  for (let ix = 0; ix < g.nx; ix += 1) {
    for (let iy = 0; iy < g.ny; iy += 1) {
      matrix.setPosition((ix - (g.nx - 1) / 2) * g.spacing[0], (iy - (g.ny - 1) / 2) * g.spacing[1], 0.1);
      dots.setMatrixAt(index, matrix);
      index += 1;
    }
  }
  group.add(dots);
  addLabel(group, item["名称"], new THREE.Vector3(-g.size[0] / 2, -g.size[1] / 2, 0.35));
  return group;
}

function renderObservationPlane(item) {
  const g = item["几何"];
  const group = new THREE.Group();
  const plane = new THREE.Mesh(
    new THREE.PlaneGeometry(g.size[0], g.size[1]),
    makeMaterial(colors.plane, 0.12)
  );
  plane.position.copy(vec3(g.center));
  group.add(plane);
  const outline = makeLine([
    [-g.size[0] / 2, -g.size[1] / 2, g.center[2]],
    [g.size[0] / 2, -g.size[1] / 2, g.center[2]],
    [g.size[0] / 2, g.size[1] / 2, g.center[2]],
    [-g.size[0] / 2, g.size[1] / 2, g.center[2]],
  ], colors.plane);
  group.add(outline);
  addLabel(group, item["名称"], new THREE.Vector3(-g.size[0] / 2, g.size[1] / 2, g.center[2] + 0.25));
  return group;
}

function renderTarget(item) {
  const g = item["几何"];
  const group = new THREE.Group();
  const shape = new THREE.Shape();
  shape.absellipse(0, 0, g.semi_axes[0], g.semi_axes[1], 0, Math.PI * 2, false, 0);
  const fill = new THREE.Mesh(new THREE.ShapeGeometry(shape), makeMaterial(colors.target, 0.22));
  fill.position.copy(vec3(g.center));
  fill.position.z += 0.04;
  fill.rotation.z = g.rotation_deg * Math.PI / 180;
  group.add(fill);
  group.add(makeLine(ellipsePoints(g.center, g.semi_axes, g.rotation_deg, 0.07), colors.target));
  group.add(makeLine(ellipsePoints(g.center, [g.semi_axes[0] * g.guard_scale, g.semi_axes[1] * g.guard_scale], g.rotation_deg, 0.03), colors.target, true));
  addLabel(group, item["名称"], vec3(g.center).add(new THREE.Vector3(0.12, 0.12, 0.42)));
  return group;
}

function renderProtected(item) {
  const g = item["几何"];
  const group = new THREE.Group();
  const shape = new THREE.Shape();
  shape.absellipse(0, 0, g.radius, g.radius, 0, Math.PI * 2, false, 0);
  const fill = new THREE.Mesh(new THREE.ShapeGeometry(shape), makeMaterial(colors.protected, 0.18));
  fill.position.copy(vec3(g.center));
  fill.position.z += 0.06;
  group.add(fill);
  group.add(makeLine(circlePoints(g.center, g.radius, 0.09), colors.protected));
  addLabel(group, item["名称"], vec3(g.center).add(new THREE.Vector3(0.12, 0.12, 0.45)));
  return group;
}

function renderReflector(item, sceneView) {
  const g = item["几何"];
  const group = new THREE.Group();
  const span = g.span;
  let geometry;
  const plane = new THREE.Mesh(undefined, makeMaterial(colors.reflector, 0.16));
  if (g.axis === "x") {
    geometry = new THREE.PlaneGeometry(span[1], span[2]);
    plane.geometry = geometry;
    plane.position.set(g.coordinate_lambda, 0, span[2] / 2);
    plane.rotation.y = Math.PI / 2;
  } else if (g.axis === "y") {
    geometry = new THREE.PlaneGeometry(span[0], span[2]);
    plane.geometry = geometry;
    plane.position.set(0, g.coordinate_lambda, span[2] / 2);
    plane.rotation.x = Math.PI / 2;
  } else {
    geometry = new THREE.PlaneGeometry(span[0], span[1]);
    plane.geometry = geometry;
    plane.position.set(0, 0, g.coordinate_lambda);
  }
  group.add(plane);
  addEdges(plane, colors.reflector);
  addLabel(group, item["名称"], new THREE.Vector3(sceneView.bounds.x[0], sceneView.bounds.y[0], span[2] + 0.4));
  return group;
}

function renderCavity(item) {
  const g = item["几何"];
  const group = new THREE.Group();
  const box = new THREE.Mesh(
    new THREE.BoxGeometry(g.size[0], g.size[1], g.size[2]),
    makeMaterial(colors.cavity, 0.18)
  );
  box.position.copy(vec3(g.center));
  group.add(box);
  addEdges(box, colors.cavity);
  addLabel(group, item["名称"], vec3(g.center).add(new THREE.Vector3(-g.size[0] / 2, -g.size[1] / 2, g.size[2] / 2 + 0.4)));
  return group;
}

function renderAperture(item) {
  const g = item["几何"];
  const group = new THREE.Group();
  const torus = new THREE.Mesh(new THREE.TorusGeometry(g.radius, Math.max(g.radius * 0.12, 0.015), 10, 40), makeMaterial(colors.aperture, 0.9));
  torus.position.copy(vec3(g.center));
  group.add(torus);
  addLabel(group, item["名称"], vec3(g.center).add(new THREE.Vector3(0.16, 0.16, 0.28)));
  return group;
}

function renderSource(item) {
  const g = item["几何"];
  const group = new THREE.Group();
  const origin = vec3(g.origin);
  const direction = vec3(g.direction).normalize();
  group.add(new THREE.ArrowHelper(direction, origin, g.length, colors.source, 0.55, 0.28));
  if (g.echo_direction) {
    group.add(new THREE.ArrowHelper(vec3(g.echo_direction).normalize(), origin, g.length * 0.82, colors.echo, 0.48, 0.24));
  }
  addLabel(group, item["名称"], direction.multiplyScalar(g.length * 0.58).add(new THREE.Vector3(0, 0, 0.35)));
  return group;
}

function renderObject(item) {
  let group;
  if (item["类型"] === "array") group = renderArray(item);
  else if (item["类型"] === "observation_plane") group = renderObservationPlane(item);
  else if (item["类型"] === "target_region") group = renderTarget(item);
  else if (item["类型"] === "protected_zone") group = renderProtected(item);
  else if (item["类型"] === "reflecting_plane") group = renderReflector(item, sceneData["视图"]);
  else if (item["类型"] === "cavity_rom") group = renderCavity(item);
  else if (item["类型"] === "aperture") group = renderAperture(item);
  else if (item["类型"] === "far_field_source") group = renderSource(item);
  else group = new THREE.Group();
  group.name = item.id;
  group.userData.objectId = item.id;
  group.userData.type = item["类型"];
  group.visible = item["启用"];
  objectGroups.set(item.id, group);
  return group;
}

function setupThree() {
  const viewport = $("三维视口");
  if (!viewport || renderer) return;
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x101820);
  camera = new THREE.PerspectiveCamera(45, 1, 0.05, 500);
  camera.up.set(0, 0, 1);
  renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setAnimationLoop(() => renderer.render(scene, camera));
  viewport.appendChild(renderer.domElement);
  raycaster = new THREE.Raycaster();
  pointer = new THREE.Vector2();
  scene.add(new THREE.HemisphereLight(0xe7eef9, 0x243044, 1.2));
  const light = new THREE.DirectionalLight(0xffffff, 1.3);
  light.position.set(6, -5, 8);
  scene.add(light);
  scene.add(new THREE.AxesHelper(1.4));
  renderer.domElement.addEventListener("pointerdown", onPointerDown);
  renderer.domElement.addEventListener("pointermove", onPointerMove);
  renderer.domElement.addEventListener("pointerup", onPointerUp);
  renderer.domElement.addEventListener("pointercancel", onPointerUp);
  renderer.domElement.addEventListener("wheel", onWheel, {passive: false});
  window.addEventListener("resize", resizeRenderer);
  resizeRenderer();
}

function resizeRenderer() {
  if (!renderer || !camera) return;
  const viewport = $("三维视口");
  if (!viewport) return;
  const rect = viewport.getBoundingClientRect();
  const width = Math.max(320, Math.floor(rect.width));
  const height = Math.max(360, Math.floor(rect.height));
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  updateCamera();
}

function updateCamera() {
  if (!camera) return;
  orbit.phi = Math.max(0.16, Math.min(1.36, orbit.phi));
  const r = orbit.radius;
  const cosPhi = Math.cos(orbit.phi);
  camera.position.set(
    orbit.target.x + r * cosPhi * Math.cos(orbit.theta),
    orbit.target.y + r * cosPhi * Math.sin(orbit.theta),
    orbit.target.z + r * Math.sin(orbit.phi)
  );
  camera.lookAt(orbit.target);
}

function rebuildScene() {
  setupThree();
  if (!sceneData || !scene) return;
  if (root) {
    root.traverse(disposeNode);
    scene.remove(root);
  }
  resultOverlay = null;
  objectGroups.clear();
  root = new THREE.Group();
  root.add(renderGrid(sceneData["视图"].bounds, sceneData["视图"].grid_step_lambda));
  sceneData["对象"].forEach((item) => root.add(renderObject(item)));
  renderResultOverlay();
  scene.add(root);
  resetCamera();
  renderObjectTree();
  renderProperties();
  updateSelection();
  updateHistoryControls();
  if ($("三维视口")) $("三维视口").classList.toggle("move-mode", moveMode);
  const stats = sceneData["统计"];
  $("三维场景摘要").textContent = `${sceneData["工程"]["名称"]} · 对象 ${stats["对象总数"]} · 启用 ${stats["启用对象数"]} · ${sceneData["阶段"]}`;
  $("三维哈希").textContent = `scene_hash: ${sceneData.scene_hash}`;
}

function resetCamera() {
  if (!sceneData) return;
  const bounds = sceneData["视图"].bounds;
  const spanX = bounds.x[1] - bounds.x[0];
  const spanY = bounds.y[1] - bounds.y[0];
  const spanZ = bounds.z[1] - bounds.z[0];
  orbit.target.set(0, 0, bounds.z[0] + spanZ * 0.46);
  orbit.radius = Math.max(spanX, spanY, spanZ) * 1.65;
  orbit.theta = -0.78;
  orbit.phi = 0.58;
  updateCamera();
}

function colorForType(type) {
  return {
    array: colors.array,
    observation_plane: colors.plane,
    target_region: colors.target,
    protected_zone: colors.protected,
    reflecting_plane: colors.reflector,
    cavity_rom: colors.cavity,
    aperture: colors.aperture,
    far_field_source: colors.source,
  }[type] || 0x6b7280;
}

function renderObjectTree() {
  const tree = $("三维对象树");
  if (!tree || !sceneData) return;
  const byId = new Map(sceneData["对象"].map((item) => [item.id, item]));
  tree.innerHTML = sceneData["对象树"].map((group) => `
    <div class="workbench3d-tree-group">
      <div class="workbench3d-tree-group-title">${group["名称"]}</div>
      ${group["对象"].map((id) => {
        const item = byId.get(id);
        if (!item) return "";
        const color = colorForType(item["类型"]).toString(16).padStart(6, "0");
        return `<button class="workbench3d-object ${item["启用"] ? "" : "off"} ${selectedId === item.id ? "active" : ""}" data-object-id="${item.id}">
          <span class="workbench3d-dot" style="background:#${color}"></span>
          <span><strong>${item["名称"]}</strong><small>${item.id} · ${item["类型"]}</small></span>
        </button>`;
      }).join("")}
    </div>`).join("");
  tree.querySelectorAll("[data-object-id]").forEach((button) => {
    button.addEventListener("click", () => selectObject(button.dataset.objectId));
  });
}

function materialOptions(selected) {
  return materialLibrary().map((material) => (
    `<option value="${escapeAttr(material.id)}" ${material.id === selected ? "selected" : ""}>${material["名称"]} · ${material.id}</option>`
  )).join("");
}

function editableInput(name, value, editable) {
  if (typeof value === "boolean") {
    return `<select data-field="${name}" ${editable ? "" : "disabled"}><option value="true" ${value ? "selected" : ""}>true</option><option value="false" ${!value ? "selected" : ""}>false</option></select>`;
  }
  if (typeof value === "number") {
    return `<input data-field="${name}" type="number" step="0.01" value="${value}" ${editable ? "" : "disabled"}>`;
  }
  if (name === "material_id" && materialLibrary().length) {
    return `<select data-field="${name}" ${editable ? "" : "disabled"}>${materialOptions(value)}</select>`;
  }
  return `<input data-field="${name}" type="text" value="${escapeAttr(value)}" ${editable ? "" : "disabled"}>`;
}

function patchFromForm(form, source, editable) {
  const patch = {};
  form.querySelectorAll("[data-field]").forEach((input) => {
    const field = input.dataset.field;
    if (!editable.has(field)) return;
    const original = source[field];
    if (typeof original === "boolean") patch[field] = input.value === "true";
    else if (typeof original === "number") patch[field] = Number(input.value);
    else patch[field] = input.value;
  });
  return patch;
}

function editableSet(item) {
  return new Set(item ? item["可编辑字段"] || [] : []);
}

function numericProperty(item, field) {
  const value = item && item["属性"] ? Number(item["属性"][field]) : NaN;
  return Number.isFinite(value) ? value : null;
}

function roundedTransformValue(value) {
  return Number(Number(value).toFixed(4));
}

function rotateValue(value, delta) {
  let next = value + delta;
  if (next > 180) next -= 360;
  if (next < -180) next += 360;
  return roundedTransformValue(next);
}

function transformCapabilities(item) {
  const editable = editableSet(item);
  const canMoveXY = editable.has("center_x_lambda") && editable.has("center_y_lambda");
  const canMoveZ = editable.has("center_z_lambda");
  const canRotate = editable.has("rotation_deg");
  const scaleFields = [
    ["semi_major_lambda", "semi_minor_lambda"],
    ["radius_lambda"],
    ["size_x_lambda", "size_y_lambda", "size_z_lambda"],
  ].find((fields) => fields.every((field) => editable.has(field) && numericProperty(item, field) !== null)) || [];
  return {canMoveXY, canMoveZ, canRotate, scaleFields};
}

function renderTransformControls(item) {
  const capabilities = transformCapabilities(item);
  if (!capabilities.canMoveXY && !capabilities.canMoveZ && !capabilities.canRotate && !capabilities.scaleFields.length) return "";
  const moveButtons = capabilities.canMoveXY ? `
    <button type="button" data-transform-action="move-left" title="X -0.1λ"><i class="bi bi-arrow-left"></i></button>
    <button type="button" data-transform-action="move-right" title="X +0.1λ"><i class="bi bi-arrow-right"></i></button>
    <button type="button" data-transform-action="move-down" title="Y -0.1λ"><i class="bi bi-arrow-down"></i></button>
    <button type="button" data-transform-action="move-up" title="Y +0.1λ"><i class="bi bi-arrow-up"></i></button>` : "";
  const zButtons = capabilities.canMoveZ ? `
    <button type="button" data-transform-action="move-z-down" title="Z -0.1λ"><i class="bi bi-arrow-down-square"></i></button>
    <button type="button" data-transform-action="move-z-up" title="Z +0.1λ"><i class="bi bi-arrow-up-square"></i></button>` : "";
  const scaleButtons = capabilities.scaleFields.length ? `
    <button type="button" data-transform-action="scale-down" title="缩小 10%"><i class="bi bi-dash-circle"></i></button>
    <button type="button" data-transform-action="scale-up" title="放大 10%"><i class="bi bi-plus-circle"></i></button>` : "";
  const rotateButtons = capabilities.canRotate ? `
    <button type="button" data-transform-action="rotate-left" title="旋转 -5°"><i class="bi bi-arrow-counterclockwise"></i></button>
    <button type="button" data-transform-action="rotate-right" title="旋转 +5°"><i class="bi bi-arrow-clockwise"></i></button>` : "";
  return `
    <div class="workbench3d-transform-controls" data-testid="workbench3d-transform-controls">
      <strong>几何变换</strong>
      <div class="workbench3d-transform-buttons">
        ${moveButtons}${zButtons}${scaleButtons}${rotateButtons}
      </div>
    </div>`;
}

function transformPatch(item, action) {
  const capabilities = transformCapabilities(item);
  const patch = {};
  const x = numericProperty(item, "center_x_lambda");
  const y = numericProperty(item, "center_y_lambda");
  const z = numericProperty(item, "center_z_lambda");
  if (capabilities.canMoveXY && x !== null && y !== null) {
    if (action === "move-left") patch.center_x_lambda = roundedTransformValue(x - 0.1);
    if (action === "move-right") patch.center_x_lambda = roundedTransformValue(x + 0.1);
    if (action === "move-down") patch.center_y_lambda = roundedTransformValue(y - 0.1);
    if (action === "move-up") patch.center_y_lambda = roundedTransformValue(y + 0.1);
  }
  if (capabilities.canMoveZ && z !== null) {
    if (action === "move-z-down") patch.center_z_lambda = roundedTransformValue(z - 0.1);
    if (action === "move-z-up") patch.center_z_lambda = roundedTransformValue(z + 0.1);
  }
  if (capabilities.scaleFields.length && (action === "scale-down" || action === "scale-up")) {
    const factor = action === "scale-up" ? 1.1 : 0.9;
    capabilities.scaleFields.forEach((field) => {
      const value = numericProperty(item, field);
      if (value !== null) patch[field] = roundedTransformValue(Math.max(value * factor, 0.005));
    });
  }
  const rotation = numericProperty(item, "rotation_deg");
  if (capabilities.canRotate && rotation !== null) {
    if (action === "rotate-left") patch.rotation_deg = rotateValue(rotation, -5);
    if (action === "rotate-right") patch.rotation_deg = rotateValue(rotation, 5);
  }
  return patch;
}

async function applyTransformAction(action) {
  const item = sceneObjectById(selectedId);
  if (!item) return;
  const patch = transformPatch(item, action);
  if (!Object.keys(patch).length) return;
  await updateObject(item.id, patch);
}

function renderMaterialEditor(materialId) {
  const materials = materialLibrary();
  if (!materials.length) {
    return `<div class="workbench3d-material-editor text-muted">材料库为空。</div>`;
  }
  const material = materialById(materialId) || materials[0];
  selectedMaterialId = material.id;
  const editable = new Set(material["可编辑字段"] || []);
  const fields = Object.entries(material["属性"] || {});
  const references = (material["引用对象"] || []).join(" · ") || "未引用";
  return `
    <div class="workbench3d-material-editor">
      <div class="workbench3d-material-summary">
        <div>
          <strong>材料库</strong>
          <small>${material["安全边界"] || ""}</small>
        </div>
        <select id="三维材料选择">${materialOptions(material.id)}</select>
      </div>
      <div class="workbench3d-property-name">${material["名称"]}</div>
      <div class="workbench3d-property-type">${material.id} · ${material["类型"]} · 引用 ${references}</div>
      <form id="三维材料表单" data-material-id="${escapeAttr(material.id)}">
        ${fields.map(([name, value]) => `<div class="workbench3d-field"><label>${name}</label>${editableInput(name, value, editable.has(name))}</div>`).join("")}
        <div class="workbench3d-actions">
          <button class="btn btn-sm btn-primary" type="submit" ${editable.size ? "" : "disabled"}><i class="bi bi-check2"></i> 应用</button>
          <button class="btn btn-sm btn-outline-secondary" type="button" id="三维还原材料"><i class="bi bi-arrow-counterclockwise"></i> 还原</button>
        </div>
      </form>
    </div>`;
}

function calibrationSummaryChips(data) {
  const power = data["功率元数据"] || {};
  const result = data["校准结果"] || {};
  const interval = result["实测距离覆盖区间_m"] || {};
  return [
    `总功率 ${formatMetric(power["总输入功率_w"], " W", 4)}`,
    `启用阵元 ${power["启用阵元数"] ?? "--"}`,
    `不均衡 ${formatMetric(power["阵元功率不均衡_db"], " dB", 2)}`,
    `系数 ${formatMetric(result["校准系数_v_per_m_per_normalized_unit"], "", 4)}`,
    `RMSE ${formatMetric(result["残差RMSE_v_per_m"], " V/m", 4)}`,
    `覆盖 ${formatMetric(result["2sigma覆盖率_percent"], "%", 1)}`,
    `实测区间 ${formatMetric(interval["最小"], " m", 2)}-${formatMetric(interval["最大"], " m", 2)}`,
  ];
}

function calibrationPowerText(data) {
  const array = data["阵列"] || sceneData?.["绝对量纲标定"]?.["阵列"] || {};
  const nx = Number(array.nx || sceneData?.["统计"]?.["阵元列数"] || 8);
  const powers = data["阵元功率"] || [];
  if (!powers.length) return "";
  const values = powers.map((item) => Number(item.power_w || 0));
  const rows = [];
  for (let i = 0; i < values.length; i += nx) {
    rows.push(values.slice(i, i + nx).map((value) => Number.isFinite(value) ? String(value) : "0").join(", "));
  }
  return rows.join("\n");
}

function calibrationPointText(data) {
  const rows = data["实测标定点"] || [];
  if (!rows.length) return "CAL-001,1.0,1.0,2.0,8";
  return rows.map((item) => [
    item.point_id || item.id || "--",
    item.distance_m ?? "",
    item.normalized_model_amplitude ?? "",
    item.measured_field_v_per_m ?? "",
    item.uncertainty_percent ?? "",
  ].join(",")).join("\n");
}

function parseNumberGrid(text) {
  return String(text || "")
    .split(/[\s,;，；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => Number(item));
}

function parseCalibrationPoints(text) {
  return String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !line.toLowerCase().startsWith("point_id"))
    .map((line, index) => {
      const cells = line.split(/[,，]/).map((item) => item.trim());
      return {
        point_id: cells[0] || `CAL-${String(index + 1).padStart(3, "0")}`,
        distance_m: Number(cells[1]),
        normalized_model_amplitude: Number(cells[2]),
        measured_field_v_per_m: Number(cells[3]),
        uncertainty_percent: Number(cells[4] || 10),
      };
    });
}

function renderAbsoluteCalibration() {
  const data = absoluteCalibration && absoluteCalibration["版本"] ? absoluteCalibration : sceneData?.["绝对量纲标定"] || {};
  const imported = assetImportedCalibration && assetImportedCalibration["版本"] ? assetImportedCalibration : sceneData?.["导入数据标定桥接"] || {};
  const importedSummary = imported["摘要"] || {};
  const checks = (data["验收清单"] || []).slice(0, 5);
  const points = (data["实测标定点"] || []).slice(0, 4);
  return `
    <div class="workbench3d-absolute-calibration" data-testid="workbench3d-absolute-calibration">
      <div class="workbench3d-calibration-head">
        <div>
          <strong>绝对量纲标定</strong>
          <small>${escapeAttr(data["安全边界"] || "阵元功率仅作为实测标定元数据，不输出作用距离或器件阈值。")}</small>
        </div>
        <span class="${data["通过"] === false ? "warn" : "ok"}">${escapeAttr(data["结论"] || "--")}</span>
      </div>
      <div class="workbench3d-calibration-summary">
        ${calibrationSummaryChips(data).map((item) => `<span>${escapeAttr(item)}</span>`).join("")}
      </div>
      <div class="workbench3d-imported-calibration-mini" data-testid="workbench3d-imported-calibration-mini">
        <strong>导入数据桥接</strong>
        <span>${escapeAttr(imported["结论"] || "--")}</span>
        <small>样本 ${escapeAttr(importedSummary["样本数"] ?? "--")} · 相对RMSE ${escapeAttr(importedSummary["标定后相对RMSE/%"] ?? "--")}% · ${importedSummary["可纳入正式可信度评分"] ? "已纳入正式评分" : "未纳入正式评分"}</small>
      </div>
      <div class="workbench3d-calibration-checks">
        ${checks.map((item) => `<span class="${item["通过"] === false ? "warn" : "ok"}">${escapeAttr(item["项目"] || "--")}</span>`).join("")}
      </div>
      <div class="workbench3d-calibration-points">
        ${points.map((item) => `
          <div>
            <strong>${escapeAttr(item.point_id || "--")}</strong>
            <small>${escapeAttr(item.distance_m ?? "--")} m · 实测 ${escapeAttr(item.measured_field_v_per_m ?? "--")} V/m · 残差 ${escapeAttr(item.residual_v_per_m ?? "--")}</small>
          </div>`).join("") || "<div><small>暂无实测标定点。</small></div>"}
      </div>
      <form id="三维绝对标定表单" class="workbench3d-calibration-form">
        <label>阵元输入功率 W（按阵列行列输入）</label>
        <textarea id="三维绝对标定功率" rows="4" spellcheck="false">${escapeAttr(calibrationPowerText(data))}</textarea>
        <label>实测点 CSV：point_id,distance_m,normalized_model_amplitude,measured_field_v_per_m,uncertainty_percent</label>
        <textarea id="三维绝对标定点" rows="4" spellcheck="false">${escapeAttr(calibrationPointText(data))}</textarea>
        <div class="workbench3d-actions">
          <button class="btn btn-sm btn-primary" type="submit"><i class="bi bi-check2"></i> 应用标定</button>
          <button class="btn btn-sm btn-outline-secondary" type="button" id="三维刷新绝对标定"><i class="bi bi-arrow-clockwise"></i> 刷新</button>
        </div>
      </form>
    </div>`;
}

async function loadAbsoluteCalibration() {
  absoluteCalibration = await requestJson("/api/workbench3d/absolute-calibration");
  assetAbsoluteCalibration = absoluteCalibration;
  if (sceneData) sceneData["绝对量纲标定"] = absoluteCalibration;
  renderProperties();
  return absoluteCalibration;
}

async function submitAbsoluteCalibration() {
  const powers = parseNumberGrid($("三维绝对标定功率")?.value || "");
  const points = parseCalibrationPoints($("三维绝对标定点")?.value || "");
  absoluteCalibration = await requestJson("/api/workbench3d/absolute-calibration", {
    method: "POST",
    body: JSON.stringify({element_powers_w: powers, calibration_points: points}),
  });
  assetAbsoluteCalibration = absoluteCalibration;
  if (sceneData) sceneData["绝对量纲标定"] = absoluteCalibration;
  renderProperties();
  await loadAssetLedger();
  const result = absoluteCalibration["校准结果"] || {};
  status(`绝对量纲标定已更新：RMSE ${formatMetric(result["残差RMSE_v_per_m"], " V/m", 4)}，不输出作用距离或器件阈值。`, absoluteCalibration["通过"] === false ? "warning" : "success");
}

function renderProperties() {
  const panel = $("三维属性面板");
  if (!panel || !sceneData) return;
  const item = sceneData["对象"].find((obj) => obj.id === selectedId) || sceneData["对象"][0];
  if (!item) {
    panel.textContent = "暂无对象。";
    return;
  }
  selectedId = item.id;
  const editable = new Set(item["可编辑字段"] || []);
  const fields = Object.entries(item["属性"] || {});
  const materialId = selectedMaterialFor(item);
  panel.innerHTML = `
    <div class="workbench3d-object-editor">
      <div class="workbench3d-property-name">${item["名称"]}</div>
      <div class="workbench3d-property-type">${item.id} · ${item["层级"]} · ${item["类型"]}</div>
      ${renderTransformControls(item)}
      <form id="三维属性表单">
        ${fields.map(([name, value]) => `<div class="workbench3d-field"><label>${name}</label>${editableInput(name, value, editable.has(name))}</div>`).join("")}
        <div class="workbench3d-actions">
          <button class="btn btn-sm btn-primary" type="submit" ${editable.size ? "" : "disabled"}><i class="bi bi-check2"></i> 应用</button>
          <button class="btn btn-sm btn-outline-secondary" type="button" id="三维还原对象"><i class="bi bi-arrow-counterclockwise"></i> 还原</button>
        </div>
      </form>
    </div>
    ${renderAbsoluteCalibration()}
    ${renderMaterialEditor(materialId)}`;
  const form = $("三维属性表单");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const patch = patchFromForm(form, item["属性"], editable);
    await updateObject(item.id, patch);
  });
  $("三维还原对象").addEventListener("click", renderProperties);
  $("三维绝对标定表单")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await submitAbsoluteCalibration();
    } catch (error) {
      status(error.message, "danger");
    }
  });
  $("三维刷新绝对标定")?.addEventListener("click", async () => {
    try {
      await loadAbsoluteCalibration();
      status("绝对量纲标定已刷新。", "success");
    } catch (error) {
      status(error.message, "danger");
    }
  });
  panel.querySelectorAll("[data-transform-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      await applyTransformAction(button.dataset.transformAction);
    });
  });
  const materialSelect = $("三维材料选择");
  if (materialSelect) {
    materialSelect.addEventListener("change", () => {
      selectedMaterialId = materialSelect.value;
      renderProperties();
    });
  }
  const materialForm = $("三维材料表单");
  if (materialForm) {
    const material = materialById(materialForm.dataset.materialId);
    const materialEditable = new Set(material ? material["可编辑字段"] || [] : []);
    materialForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!material) return;
      const patch = patchFromForm(materialForm, material["属性"], materialEditable);
      await updateMaterial(material.id, patch);
    });
    $("三维还原材料")?.addEventListener("click", renderProperties);
  }
}

function selectObject(objectId) {
  selectedId = objectId;
  const item = sceneObjectById(objectId);
  if (item && item["材料"]) selectedMaterialId = item["材料"];
  renderObjectTree();
  renderProperties();
  updateSelection();
}

function updateSelection() {
  if (selectionBox) {
    scene.remove(selectionBox);
    selectionBox = null;
  }
  const group = objectGroups.get(selectedId);
  if (!group || !scene) return;
  selectionBox = new THREE.BoxHelper(group, colors.selected);
  scene.add(selectionBox);
}

async function loadScene() {
  try {
    status("正在载入三维工程场景。", "info");
    sceneData = await requestJson("/api/workbench3d/scene");
    absoluteCalibration = sceneData["绝对量纲标定"] || {};
    assetAbsoluteCalibration = absoluteCalibration;
    assetImportedCalibration = sceneData["导入数据标定桥接"] || {};
    if (!selectedId && sceneData["对象"].length) selectedId = sceneData["对象"][0].id;
    if (!selectedMaterialId && materialLibrary().length) selectedMaterialId = materialLibrary()[0].id;
    rebuildScene();
    renderSolveResult();
    await loadResultArchive();
    await loadSolveJobs();
    await loadSnapshotArchive();
    await loadAssetLedger();
    status(`三维场景已载入：${sceneData["校验"]["检查"].join("；")}。`, "success");
  } catch (error) {
    status(error.message, "danger");
  }
}

async function updateObject(objectId, properties) {
  try {
    status("正在提交三维对象更新。", "info");
    sceneData = await requestJson(`/api/workbench3d/objects/${encodeURIComponent(objectId)}`, {
      method: "POST",
      body: JSON.stringify({properties}),
    });
    selectedId = objectId;
    const current = sceneObjectById(objectId);
    if (current && current["材料"]) selectedMaterialId = current["材料"];
    solveData = null;
    rebuildScene();
    renderSolveResult();
    status("三维对象已通过后端几何校验并更新。", "success");
  } catch (error) {
    rebuildScene();
    status(error.message, "danger");
  }
}

async function updateMaterial(materialId, properties) {
  try {
    status("正在提交材料代理更新。", "info");
    sceneData = await requestJson(`/api/workbench3d/materials/${encodeURIComponent(materialId)}`, {
      method: "POST",
      body: JSON.stringify({properties}),
    });
    selectedMaterialId = materialId;
    solveData = null;
    rebuildScene();
    renderSolveResult();
    status("材料代理已通过工程模型校验并更新。", "success");
  } catch (error) {
    rebuildScene();
    status(error.message, "danger");
  }
}

async function resetSceneFromProject() {
  try {
    sceneData = await requestJson("/api/workbench3d/reset", {method: "POST"});
    selectedId = sceneData["对象"].length ? sceneData["对象"][0].id : null;
    selectedMaterialId = materialLibrary().length ? materialLibrary()[0].id : null;
    solveData = null;
    rebuildScene();
    renderSolveResult();
    status("三维场景已从工程配置重载。", "success");
  } catch (error) {
    status(error.message, "danger");
  }
}

async function solveWorkbenchScene() {
  const button = $("三维运行求解");
  try {
    if (button) button.disabled = true;
    status("正在提交三维求解任务。", "info");
    const jobResponse = await requestJson("/api/workbench3d/solve-jobs", {
      method: "POST",
      body: JSON.stringify({label: `V2.0B-${new Date().toLocaleTimeString("zh-CN", {hour12: false})}`}),
    });
    solveData = jobResponse["结果"] || null;
    solveJobs = jobResponse["队列"] || (jobResponse["任务"] ? [jobResponse["任务"]] : solveJobs);
    solveJobAudit = jobResponse["审计"] || solveJobAudit;
    renderSolveResult();
    renderResultOverlay();
    renderSolveJobs();
    await loadResultArchive();
    await loadAssetLedger();
    status(`三维求解任务 ${jobResponse["任务"]?.id || "--"} 已完成，结果已写入当前页面。`, "success");
  } catch (error) {
    status(error.message, "danger");
  } finally {
    if (button) button.disabled = false;
  }
}

function exportSnapshot() {
  if (!sceneData) return;
  const blob = new Blob([JSON.stringify(sceneData, null, 2)], {type: "application/json;charset=utf-8"});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `HPM-DT_${sceneData["版本"]}_${sceneData.scene_hash}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

async function undoSceneEdit() {
  try {
    sceneData = await requestJson("/api/workbench3d/undo", {method: "POST"});
    solveData = null;
    rebuildScene();
    renderSolveResult();
    status("已撤销上一步三维编辑。", "success");
  } catch (error) {
    status(error.message, "warning");
  }
}

async function redoSceneEdit() {
  try {
    sceneData = await requestJson("/api/workbench3d/redo", {method: "POST"});
    solveData = null;
    rebuildScene();
    renderSolveResult();
    status("已重做三维编辑。", "success");
  } catch (error) {
    status(error.message, "warning");
  }
}

async function captureServerSnapshot() {
  try {
    const result = await requestJson("/api/workbench3d/snapshots", {
      method: "POST",
      body: JSON.stringify({label: `V2.0B-${new Date().toLocaleTimeString("zh-CN", {hour12: false})}`}),
    });
    if (sceneData) {
      sceneData["历史"] = result["历史"];
      updateHistoryControls();
    }
    await loadSnapshotArchive();
    await loadAssetLedger();
    status(`已保存工程快照 ${result["快照"].id} · ${result["快照"].scene_hash}`, "success");
  } catch (error) {
    status(error.message, "danger");
  }
}

function objectFromPointer(event) {
  if (!renderer || !camera || !raycaster || !pointer) return null;
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects([...objectGroups.values()], true);
  for (const hit of hits) {
    let node = hit.object;
    while (node) {
      if (node.userData && node.userData.objectId) return node.userData.objectId;
      node = node.parent;
    }
  }
  return null;
}

function pointOnZPlane(event, zValue) {
  if (!renderer || !camera || !raycaster || !pointer) return null;
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  dragPlane.constant = -zValue;
  const hit = raycaster.ray.intersectPlane(dragPlane, dragPoint);
  return hit ? dragPoint.clone() : null;
}

function centerOfObject(item) {
  const center = item && item["几何"] ? item["几何"].center : null;
  if (Array.isArray(center) && center.length >= 3) return {x: Number(center[0]), y: Number(center[1]), z: Number(center[2])};
  return null;
}

function startMoveDrag(event, objectId) {
  const item = sceneObjectById(objectId);
  const center = centerOfObject(item);
  if (!isDraggableObject(item) || !center) return false;
  const point = pointOnZPlane(event, center.z);
  const group = objectGroups.get(objectId);
  if (!point || !group) return false;
  activeMove = {
    objectId,
    startPoint: point,
    startCenter: center,
    group,
    z: center.z,
  };
  $("三维视口")?.classList.add("dragging");
  renderer.domElement.setPointerCapture(event.pointerId);
  status(`正在移动 ${item["名称"]}，松手后提交几何校验。`, "info");
  return true;
}

function previewMoveDrag(event) {
  if (!activeMove) return;
  const point = pointOnZPlane(event, activeMove.z);
  if (!point) return;
  const dx = point.x - activeMove.startPoint.x;
  const dy = point.y - activeMove.startPoint.y;
  activeMove.group.position.set(dx, dy, 0);
  if (selectionBox) selectionBox.update();
}

async function finishMoveDrag(event) {
  if (!activeMove) return;
  const move = activeMove;
  activeMove = null;
  $("三维视口")?.classList.remove("dragging");
  const point = pointOnZPlane(event, move.z);
  if (!point) {
    rebuildScene();
    return;
  }
  const dx = point.x - move.startPoint.x;
  const dy = point.y - move.startPoint.y;
  const nextX = snapLambda(move.startCenter.x + dx);
  const nextY = snapLambda(move.startCenter.y + dy);
  await updateObject(move.objectId, {center_x_lambda: nextX, center_y_lambda: nextY});
}

function onPointerDown(event) {
  const objectId = objectFromPointer(event);
  if (objectId) selectObject(objectId);
  if (objectId && moveMode && startMoveDrag(event, objectId)) {
    event.preventDefault();
    return;
  }
  isDragging = true;
  dragStart = {x: event.clientX, y: event.clientY, theta: orbit.theta, phi: orbit.phi};
  renderer.domElement.setPointerCapture(event.pointerId);
}

function onPointerMove(event) {
  if (activeMove) {
    previewMoveDrag(event);
    event.preventDefault();
    return;
  }
  if (!isDragging) return;
  const dx = event.clientX - dragStart.x;
  const dy = event.clientY - dragStart.y;
  orbit.theta = dragStart.theta - dx * 0.006;
  orbit.phi = dragStart.phi + dy * 0.004;
  updateCamera();
}

async function onPointerUp(event) {
  if (activeMove) {
    await finishMoveDrag(event);
  }
  isDragging = false;
  try {
    renderer.domElement.releasePointerCapture(event.pointerId);
  } catch (_) {
    // Pointer capture may already be released by the browser.
  }
}

function onWheel(event) {
  event.preventDefault();
  orbit.radius *= event.deltaY > 0 ? 1.08 : 0.92;
  orbit.radius = Math.max(3, Math.min(80, orbit.radius));
  updateCamera();
}

window.addEventListener("DOMContentLoaded", () => {
  if (!$("三维视口")) return;
  $("三维移动模式").addEventListener("click", () => setMoveMode(!moveMode));
  $("三维撤销").addEventListener("click", undoSceneEdit);
  $("三维重做").addEventListener("click", redoSceneEdit);
  $("三维保存快照").addEventListener("click", captureServerSnapshot);
  $("三维重载场景").addEventListener("click", resetSceneFromProject);
  $("三维重置相机").addEventListener("click", resetCamera);
  $("三维导出快照").addEventListener("click", exportSnapshot);
  $("三维运行求解").addEventListener("click", solveWorkbenchScene);
  $("三维求解任务").addEventListener("click", onSolveJobClick);
  $("三维结果档案").addEventListener("click", onResultArchiveClick);
  $("三维工程快照").addEventListener("click", onSnapshotArchiveClick);
  $("三维资产台账").addEventListener("click", onAssetLedgerClick);
  $("三维资产台账").addEventListener("keydown", onAssetLedgerKeydown);
  $("三维求解结果").addEventListener("click", onObjectMetricClick);
  $("三维求解结果").addEventListener("click", onProfileAxisClick);
  renderSolveResult();
  renderSolveJobs();
  renderResultArchive();
  renderSnapshotArchive();
  renderAssetLedger();
  loadScene();
});
