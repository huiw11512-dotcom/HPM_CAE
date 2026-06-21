"""V2.0 Scene First 工作台服务层。"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time
from typing import Any

from hpm_platform.data_import import (
    DataImportService,
    generate_calibration_bridge_report,
    generate_evidence_chain_report,
    generate_evidence_package_template,
    generate_evidence_package_vv_candidate,
    generate_external_data_vv_audit,
    generate_model_comparison_report,
    inspect_evidence_package,
)
from hpm_platform.north_star import platform_north_star_payload
from hpm_platform.plugins import PluginMarketplaceService
from hpm_platform.publication import PaperFactoryService
from hpm_platform.readiness import build_platform_readiness_report, load_readiness_config
from hpm_platform.ui.workbench3d import Workbench3DService
from hpm_platform.validation.vv_runner import load_last_vv_result, run_vv


class V20AValidationService:
    """为 FastAPI UI 提供线程安全的 V&V 运行和结果缓存。"""

    def __init__(self, project_path: str | Path, output_dir: str | Path):
        self.project_path = Path(project_path)
        self.output_dir = Path(output_dir)
        self._lock = threading.RLock()
        self._payload: dict[str, Any] | None = None
        self.workbench3d = Workbench3DService(self.project_path, self.output_dir)
        self.plugins = PluginMarketplaceService(output_dir=self.output_dir)
        self.paper_factory = PaperFactoryService(self.output_dir)
        self.data_import = DataImportService(self.output_dir)
        self.logs: list[str] = []

    def _log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.logs.append(f"[{stamp}] {message}")
        self.logs = self.logs[-100:]

    def run(self, mode: str = "fast") -> dict[str, Any]:
        with self._lock:
            normalized = "full" if str(mode).lower() == "full" else "fast"
            self._log(f"开始运行{('完整' if normalized == 'full' else '快速')}V&V")
            payload = run_vv(
                mode=normalized,
                project_path=self.project_path,
                output_dir=self.output_dir,
                include_plotly=True,
            )
            self._payload = payload
            self._log(f"V&V完成：评分 {payload['score']['可信度评分']}，等级 {payload['score']['当前等级']}")
            return self._ui_payload(payload)

    def overview(self) -> dict[str, Any]:
        with self._lock:
            if self._payload is None:
                last = load_last_vv_result(self.output_dir)
                if last is None:
                    return self.run("fast")
                self._log("读取最近一次V&V结果，并刷新交互图")
                return self.run("fast")
            return self._ui_payload(self._payload)

    def north_star_payload(self) -> dict[str, Any]:
        return platform_north_star_payload()

    def data_import_calibration_bridge(self) -> dict[str, Any]:
        with self._lock:
            return generate_calibration_bridge_report(
                self.project_path,
                self.output_dir,
                self.data_import,
            )

    def data_import_model_comparison(self) -> dict[str, Any]:
        with self._lock:
            return generate_model_comparison_report(
                self.project_path,
                self.output_dir,
                self.data_import,
            )

    def data_import_evidence_chain(self) -> dict[str, Any]:
        with self._lock:
            return generate_evidence_chain_report(self.output_dir)

    def data_import_evidence_package(self, path: str | Path) -> dict[str, Any]:
        with self._lock:
            return inspect_evidence_package(path, self.output_dir)

    def data_import_evidence_package_template(self) -> dict[str, Any]:
        with self._lock:
            return generate_evidence_package_template(self.output_dir)

    def data_import_evidence_package_vv_candidate(self, path: str | Path) -> dict[str, Any]:
        with self._lock:
            base_score = None
            if self._payload is not None:
                base_score = self._payload.get("score", {}).get("可信度评分")
            return generate_evidence_package_vv_candidate(
                self.project_path,
                path,
                self.output_dir,
                self.data_import,
                base_credibility_score=base_score,
            )

    def data_import_vv_audit(self) -> dict[str, Any]:
        with self._lock:
            base_score = None
            if self._payload is not None:
                base_score = self._payload.get("score", {}).get("可信度评分")
            return generate_external_data_vv_audit(
                self.project_path,
                self.output_dir,
                self.data_import,
                base_credibility_score=base_score,
            )

    def data_import_latest_evidence_package_vv_candidate(self) -> dict[str, Any]:
        with self._lock:
            report_path = self.output_dir / "data_import_v30" / "evidence_package_vv_candidate.json"
            if report_path.exists():
                return json.loads(report_path.read_text(encoding="utf-8"))
            template = generate_evidence_package_template(self.output_dir)
            base_score = None
            if self._payload is not None:
                base_score = self._payload.get("score", {}).get("可信度评分")
            return generate_evidence_package_vv_candidate(
                self.project_path,
                template.get("输出文件", ""),
                self.output_dir,
                self.data_import,
                base_credibility_score=base_score,
            )

    def ensure_workbench_imported_calibration_bridge(self) -> dict[str, Any]:
        with self._lock:
            self.data_import_calibration_bridge()
            self.data_import_model_comparison()
            self.data_import_vv_audit()
            return self.workbench3d.imported_calibration_bridge()

    def platform_readiness(self) -> dict[str, Any]:
        """Generate a North Star platform maturity and publication-readiness report."""

        with self._lock:
            vv_payload = self.overview()
            bridge = self.data_import_calibration_bridge()
            comparison = self.data_import_model_comparison()
            evidence_chain = self.data_import_evidence_chain()
            external_audit = self.data_import_vv_audit()
            evidence_candidate = self.data_import_latest_evidence_package_vv_candidate()
            imported_bridge = self.ensure_workbench_imported_calibration_bridge()
            scene = self.workbench3d.scene()
            assets = self.workbench3d.list_assets()
            material_audit = assets.get("材料代理审计", {})
            if not any(item.get("类型") == "求解结果" for item in assets.get("资产", ()) if isinstance(item, dict)):
                self.workbench3d.submit_solve_job("平台成熟度基线求解")
                assets = self.workbench3d.list_assets()
                material_audit = assets.get("材料代理审计", {})
            paper_status = self.paper_factory.status()
            if not paper_status.get("通过"):
                paper_status = self.paper_factory.generate()
            data_catalog = self.data_import.catalog()
            readiness_config = load_readiness_config()
            return build_platform_readiness_report(
                output_dir=self.output_dir,
                north_star=self.north_star_payload(),
                vv=vv_payload,
                workbench={
                    "scene": scene,
                    "assets": assets,
                    "imported_calibration": imported_bridge,
                    "material_audit": material_audit,
                },
                data_import={
                    "catalog": data_catalog,
                    "readiness": self.data_import.calibration_readiness(),
                    "bridge": bridge,
                    "model_comparison": comparison,
                    "evidence_chain": evidence_chain,
                    "vv_audit": external_audit,
                    "evidence_package_vv_candidate": evidence_candidate,
                },
                plugins={
                    "catalog": self.plugins.catalog(),
                    "acceptance": self.plugins.acceptance_summary(),
                },
                paper_factory=paper_status,
                readiness_config=readiness_config,
            )

    def mission_control(self) -> dict[str, Any]:
        """Return a visible end-to-end platform control-room summary for the UI."""

        with self._lock:
            readiness = self.platform_readiness()
            vv_payload = self.overview()
            plugin_catalog = self.plugins.catalog()
            data_catalog = self.data_import.catalog()
            paper_status = self.paper_factory.status()
            score = vv_payload.get("评分", {})
            summary = {
                "可信度评分": score.get("可信度评分", "—"),
                "可信度等级": score.get("当前等级", "—"),
                "使用准备度/%": readiness.get("使用准备度/%", 0),
                "发文准备度/%": readiness.get("发文准备度/%", 0),
                "平台成熟度/%": readiness.get("平台成熟度/%", 0),
                "插件数": plugin_catalog.get("插件总数", 0),
                "插件类别数": plugin_catalog.get("类别总数", 0),
                "数据样例数": data_catalog.get("样例数", 0),
                "论文工厂状态": paper_status.get("状态", "未知"),
            }
            workflow = []
            for index, item in enumerate(readiness.get("主链路", ()), start=1):
                if not isinstance(item, dict):
                    continue
                step = str(item.get("步骤", ""))
                workflow.append(
                    {
                        "序号": index,
                        "步骤": step,
                        "状态": item.get("状态", "待补齐"),
                        "通过": bool(item.get("通过")),
                        "入口": _workflow_entry(step),
                        "证据": item.get("证据", ""),
                    }
                )
            return {
                "版本": "MissionControl-v1",
                "更新时间UTC": datetime.now(timezone.utc).isoformat(),
                "平台": readiness.get("平台", "HPM-DT"),
                "结论": readiness.get("结论", ""),
                "总览": summary,
                "主链路": workflow,
                "可用入口": [
                    {"入口": "三维CAE编辑器", "状态": _entry_state(workflow, "三维CAE编辑器"), "证据": "Three.js 视口、对象树、属性面板与求解档案"},
                    {"入口": "插件市场", "状态": "已接通" if plugin_catalog.get("插件总数", 0) else "待补齐", "证据": f"{plugin_catalog.get('插件总数', 0)} 个插件，{plugin_catalog.get('类别总数', 0)} 类"},
                    {"入口": "数据导入", "状态": "已接通" if data_catalog.get("样例数", 0) else "待补齐", "证据": f"{data_catalog.get('样例数', 0)} 个样例，支持 {', '.join(data_catalog.get('支持格式', []) or [])}"},
                    {"入口": "论文报告导出", "状态": "已接通" if paper_status.get("通过") else "待补齐", "证据": paper_status.get("状态", "未知")},
                    {"入口": "平台成熟度", "状态": "已接通", "证据": readiness.get("产物", {}).get("json", "平台成熟度报告")},
                ],
                "近期差距": list(readiness.get("关键阻断项", ()))[:8],
                "快速动作": [
                    {"名称": "运行快速V&V", "入口": "验证总览", "动作": "run_fast_vv", "说明": "刷新可信度评分和图表。"},
                    {"名称": "打开三维CAE编辑器", "入口": "三维CAE编辑器", "动作": "open_page", "说明": "编辑对象、材料代理和求解预览。"},
                    {"名称": "运行数据导入证据链插件", "入口": "插件市场", "动作": "run_data_import_plugin", "说明": "检查外部数据证据链与相位参考状态。"},
                    {"名称": "生成论文草稿包", "入口": "论文报告导出", "动作": "generate_paper", "说明": "输出 Markdown、LaTeX、图表索引和补充材料。"},
                    {"名称": "刷新平台成熟度", "入口": "平台成熟度", "动作": "refresh_readiness", "说明": "更新使用准备度、发文准备度和阻断项。"},
                ],
                "产物": {
                    "平台成熟度JSON": readiness.get("产物", {}).get("json"),
                    "平台成熟度CSV": readiness.get("产物", {}).get("csv"),
                    "论文包ZIP": paper_status.get("产物", {}).get("论文包ZIP") if isinstance(paper_status.get("产物"), dict) else None,
                },
                "安全边界": readiness.get("安全边界", {}),
            }

    def _ui_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        summary = payload["summary"]
        score = payload["score"]
        cards = [
            {"标签": "总测试数", "数值": summary["总测试数"], "说明": "自动验证用例", "状态": "通过"},
            {"标签": "通过数", "数值": summary["通过数"], "说明": f"通过率 {summary['通过率']:.1f}%", "状态": "通过"},
            {"标签": "失败数", "数值": summary["失败数"], "说明": "需后续改进项", "状态": "通过" if summary["失败数"] == 0 else "关注"},
            {"标签": "可信度评分", "数值": score["可信度评分"], "说明": "0-100 归一化评分", "状态": "通过" if score["可信度评分"] >= 85 else "关注"},
            {"标签": "当前等级", "数值": score["当前等级"], "说明": "A/B/C/D", "状态": "通过" if score["当前等级"] in {"A", "B"} else "关注"},
            {"标签": "运行模式", "数值": payload["mode"], "说明": "快速或完整", "状态": "提示"},
        ]
        external_data_vv = payload.get("external_data_vv") or {}
        if external_data_vv:
            cards.append(
                {
                    "标签": "外部数据预评分",
                    "数值": external_data_vv.get("预评分", "—"),
                    "说明": "V3.0 导入数据风险附注",
                    "状态": "通过" if external_data_vv.get("可纳入正式可信度评分") else "关注",
                }
            )
        return {
            "成功": True,
            "版本": payload["version"],
            "平台愿景": self.north_star_payload(),
            "卡片": cards,
            "摘要": summary,
            "评分": score,
            "用例": payload["cases"],
            "不确定度": payload["uncertainty"]["汇总"],
            "敏感性": payload["sensitivity"]["记录"],
            "外部数据V&V": external_data_vv,
            "图形": payload.get("plotly", {}),
            "输出": payload["outputs"],
            "运行日志": list(self.logs[-60:]),
        }


def _workflow_entry(step: str) -> str:
    if any(token in step for token in ("新建", "加载", "拖拽", "设置材料", "运行求解")):
        return "三维CAE编辑器"
    if "验证" in step:
        return "验证总览"
    if "数据" in step or "评分" in step:
        return "数据导入"
    if "图表" in step or "论文" in step:
        return "论文报告导出"
    return "平台成熟度"


def _entry_state(workflow: list[dict[str, Any]], entry: str) -> str:
    related = [item for item in workflow if item.get("入口") == entry]
    if not related:
        return "待补齐"
    return "已接通" if any(item.get("通过") for item in related) else "待补齐"
