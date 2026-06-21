"""V2.0A 可信度验证中心服务层。"""
from __future__ import annotations

from pathlib import Path
import threading
import time
from typing import Any

from hpm_platform.data_import import (
    DataImportService,
    generate_calibration_bridge_report,
    generate_evidence_chain_report,
    generate_external_data_vv_audit,
    generate_model_comparison_report,
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
            imported_bridge = self.ensure_workbench_imported_calibration_bridge()
            scene = self.workbench3d.scene()
            assets = self.workbench3d.list_assets()
            if not any(item.get("类型") == "求解结果" for item in assets.get("资产", ()) if isinstance(item, dict)):
                self.workbench3d.submit_solve_job("平台成熟度基线求解")
                assets = self.workbench3d.list_assets()
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
                },
                data_import={
                    "catalog": data_catalog,
                    "readiness": self.data_import.calibration_readiness(),
                    "bridge": bridge,
                    "model_comparison": comparison,
                    "evidence_chain": evidence_chain,
                    "vv_audit": external_audit,
                },
                plugins={
                    "catalog": self.plugins.catalog(),
                    "acceptance": self.plugins.acceptance_summary(),
                },
                paper_factory=paper_status,
                readiness_config=readiness_config,
            )

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
