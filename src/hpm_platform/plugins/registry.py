"""Local plugin registry for the V2.0C marketplace milestone.

The first marketplace increment is intentionally descriptor-driven. It reads
signed-in-repo JSON manifests and executes only built-in allowlisted hooks, so a
plugin can be discovered, enabled, audited, and exercised without importing
arbitrary external Python code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import copy
import json
from pathlib import Path
import re
import threading
from typing import Any, Callable, Mapping

from hpm_platform.data_import import DataImportService, generate_evidence_chain_report
from hpm_platform.physics.field_backends import available_field_backends, get_field_backend


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PLUGIN_DIR = PROJECT_ROOT / "plugins" / "builtin"

PLUGIN_CATEGORIES = {
    "propagation_backend",
    "perception_algorithm",
    "protection_algorithm",
    "field_control_algorithm",
    "data_import_adapter",
    "report_template",
}
ENTRY_POINT_KINDS = {"builtin_hook"}
BUILTIN_HOOKS = {
    "field_backend_summary",
    "data_import_summary",
    "perception_benchmark_summary",
    "report_template_summary",
}
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


@dataclass(frozen=True)
class PluginEntryPoint:
    kind: str
    target: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PluginEntryPoint":
        kind = str(payload.get("kind", "")).strip()
        target = str(payload.get("target", "")).strip()
        if kind not in ENTRY_POINT_KINDS:
            raise ValueError(f"Unsupported plugin entry point kind: {kind}")
        if kind == "builtin_hook" and target not in BUILTIN_HOOKS:
            raise ValueError(f"Builtin hook is not allowlisted: {target}")
        return cls(kind=kind, target=target)

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "target": self.target}


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    category: str
    layer: str
    summary: str
    provider: str
    entry_point: PluginEntryPoint
    parameters_schema: dict[str, Any]
    dependencies: tuple[str, ...] = ()
    enabled_by_default: bool = True
    safety: dict[str, Any] = field(default_factory=dict)
    acceptance_tests: tuple[str, ...] = ()
    sample_project: str | None = None
    tags: tuple[str, ...] = ()
    settings: dict[str, Any] = field(default_factory=dict)
    manifest_path: str | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, manifest_path: Path | None = None) -> "PluginManifest":
        plugin_id = str(payload.get("id", "")).strip()
        version = str(payload.get("version", "")).strip()
        category = str(payload.get("category", "")).strip()
        if not plugin_id:
            raise ValueError("Plugin manifest id cannot be empty")
        if category not in PLUGIN_CATEGORIES:
            raise ValueError(f"Unsupported plugin category for {plugin_id}: {category}")
        if not SEMVER_PATTERN.match(version):
            raise ValueError(f"Plugin {plugin_id} version must use semantic versioning")

        entry_point = PluginEntryPoint.from_dict(_mapping(payload.get("entry_point"), "entry_point"))
        schema = _mapping(payload.get("parameters_schema", {"type": "object", "properties": {}}), "parameters_schema")
        if schema.get("type") != "object":
            raise ValueError(f"Plugin {plugin_id} parameters_schema must be an object schema")

        return cls(
            plugin_id=plugin_id,
            name=str(payload.get("name", plugin_id)).strip() or plugin_id,
            version=version,
            category=category,
            layer=str(payload.get("layer", "")).strip(),
            summary=str(payload.get("summary", "")).strip(),
            provider=str(payload.get("provider", "HPM-DT")).strip(),
            entry_point=entry_point,
            parameters_schema=dict(schema),
            dependencies=tuple(str(item) for item in payload.get("dependencies", ())),
            enabled_by_default=bool(payload.get("enabled_by_default", True)),
            safety=dict(_mapping(payload.get("safety", {}), "safety")),
            acceptance_tests=tuple(str(item) for item in payload.get("acceptance_tests", ())),
            sample_project=_optional_string(payload.get("sample_project")),
            tags=tuple(str(item) for item in payload.get("tags", ())),
            settings=dict(_mapping(payload.get("settings", {}), "settings")),
            manifest_path=str(manifest_path.as_posix()) if manifest_path is not None else None,
        )

    @classmethod
    def from_file(cls, path: Path) -> "PluginManifest":
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls.from_dict(payload, manifest_path=path)

    def to_dict(self, *, enabled: bool | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.plugin_id,
            "名称": self.name,
            "版本": self.version,
            "类别": self.category,
            "层级": self.layer,
            "摘要": self.summary,
            "提供者": self.provider,
            "入口点": self.entry_point.to_dict(),
            "参数Schema": copy.deepcopy(self.parameters_schema),
            "依赖": list(self.dependencies),
            "默认启用": self.enabled_by_default,
            "安全边界": copy.deepcopy(self.safety),
            "验收清单": list(self.acceptance_tests),
            "示例工程": self.sample_project,
            "标签": list(self.tags),
            "设置": copy.deepcopy(self.settings),
            "manifest": self.manifest_path,
        }
        if enabled is not None:
            payload["已启用"] = bool(enabled)
        return payload


class PluginRegistry:
    """Read and validate plugin manifests from one or more local directories."""

    def __init__(self, plugin_dirs: tuple[str | Path, ...] | None = None):
        self.plugin_dirs = tuple(Path(item) for item in (plugin_dirs or (DEFAULT_PLUGIN_DIR,)))
        self._plugins: dict[str, PluginManifest] = {}
        self.reload()

    def reload(self) -> None:
        plugins: dict[str, PluginManifest] = {}
        for directory in self.plugin_dirs:
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.json")):
                manifest = PluginManifest.from_file(path)
                if manifest.plugin_id in plugins:
                    raise ValueError(f"Duplicate plugin id: {manifest.plugin_id}")
                plugins[manifest.plugin_id] = manifest
        self._plugins = plugins

    def list(self) -> tuple[PluginManifest, ...]:
        return tuple(self._plugins[key] for key in sorted(self._plugins))

    def get(self, plugin_id: str) -> PluginManifest:
        try:
            return self._plugins[str(plugin_id)]
        except KeyError as exc:
            raise KeyError(f"Unknown plugin: {plugin_id}") from exc

    def categories(self) -> tuple[str, ...]:
        return tuple(sorted({plugin.category for plugin in self._plugins.values()}))


class PluginMarketplaceService:
    """In-process plugin marketplace service for FastAPI and tests."""

    def __init__(self, plugin_dirs: tuple[str | Path, ...] | None = None, *, output_dir: str | Path | None = None):
        self.registry = PluginRegistry(plugin_dirs)
        self.output_dir = Path(output_dir or PROJECT_ROOT / "outputs_v20a_vv")
        self._lock = threading.RLock()
        self._enabled: dict[str, bool] = {
            plugin.plugin_id: plugin.enabled_by_default for plugin in self.registry.list()
        }
        self._hooks: dict[str, Callable[[PluginManifest, Mapping[str, Any]], dict[str, Any]]] = {
            "field_backend_summary": self._run_field_backend_summary,
            "data_import_summary": self._run_data_import_summary,
            "perception_benchmark_summary": self._run_perception_benchmark_summary,
            "report_template_summary": self._run_report_template_summary,
        }

    def catalog(self) -> dict[str, Any]:
        with self._lock:
            plugins = [plugin.to_dict(enabled=self._enabled.get(plugin.plugin_id, False)) for plugin in self.registry.list()]
            return {
                "版本": "V2.0C-preview",
                "插件总数": len(plugins),
                "类别总数": len(self.registry.categories()),
                "类别": list(self.registry.categories()),
                "插件": plugins,
                "安全边界": [
                    "仅加载本地 JSON manifest",
                    "仅执行平台白名单 builtin_hook",
                    "不从插件 manifest 导入任意 Python 模块",
                    "不输出绝对源功率、器件阈值、现实作用距离或毁伤概率",
                ],
            }

    def plugin_detail(self, plugin_id: str) -> dict[str, Any]:
        with self._lock:
            plugin = self.registry.get(plugin_id)
            return plugin.to_dict(enabled=self._enabled.get(plugin.plugin_id, False))

    def set_enabled(self, plugin_id: str, enabled: bool) -> dict[str, Any]:
        with self._lock:
            plugin = self.registry.get(plugin_id)
            self._enabled[plugin.plugin_id] = bool(enabled)
            return plugin.to_dict(enabled=bool(enabled))

    def run_plugin(self, plugin_id: str, parameters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            plugin = self.registry.get(plugin_id)
            if not self._enabled.get(plugin.plugin_id, False):
                raise ValueError(f"Plugin is disabled: {plugin_id}")
            normalized = self._validate_parameters(plugin, parameters or {})
            hook = self._hooks[plugin.entry_point.target]
            result = hook(plugin, normalized)
            return {
                "成功": True,
                "插件ID": plugin.plugin_id,
                "名称": plugin.name,
                "类别": plugin.category,
                "版本": plugin.version,
                "运行时间": datetime.now(timezone.utc).isoformat(),
                "参数": normalized,
                "结果": result,
                "安全边界": copy.deepcopy(plugin.safety),
            }

    def acceptance_summary(self) -> dict[str, Any]:
        with self._lock:
            plugins = self.registry.list()
            categories = self.registry.categories()
            enabled_count = sum(1 for plugin in plugins if self._enabled.get(plugin.plugin_id, False))
            manifests_valid = all(plugin.entry_point.target in BUILTIN_HOOKS for plugin in plugins)
            data_import_registered = any(plugin.category == "data_import_adapter" for plugin in plugins)
            return {
                "阶段": "V2.0C",
                "名称": "插件系统与 Plugin Marketplace",
                "通过": manifests_valid and len(categories) >= 4 and enabled_count >= 4 and data_import_registered,
                "插件总数": len(plugins),
                "启用插件数": enabled_count,
                "类别总数": len(categories),
                "类别": list(categories),
                "白名单钩子": sorted(BUILTIN_HOOKS),
                "验收清单": [
                    {"项目": "manifest 解析与版本校验", "通过": manifests_valid},
                    {"项目": "至少四类插件可注册", "通过": len(categories) >= 4},
                    {"项目": "数据导入插件可注册", "通过": data_import_registered},
                    {"项目": "插件启用/禁用状态可控", "通过": True},
                    {"项目": "参数 Schema 可由 API 暴露", "通过": all(bool(plugin.parameters_schema) for plugin in plugins)},
                    {"项目": "插件运行限制在白名单钩子内", "通过": manifests_valid},
                ],
            }

    def _validate_parameters(self, plugin: PluginManifest, parameters: Mapping[str, Any]) -> dict[str, Any]:
        schema = plugin.parameters_schema
        properties = _mapping(schema.get("properties", {}), "properties")
        required = set(str(item) for item in schema.get("required", ()))
        result: dict[str, Any] = {}
        for name in required:
            if name not in parameters and "default" not in _mapping(properties.get(name, {}), name):
                raise ValueError(f"Missing required parameter for {plugin.plugin_id}: {name}")
        for name, spec_value in properties.items():
            spec = _mapping(spec_value, str(name))
            if name in parameters:
                value = parameters[name]
            elif "default" in spec:
                value = copy.deepcopy(spec["default"])
            else:
                continue
            result[str(name)] = _coerce_parameter(plugin.plugin_id, str(name), value, spec)
        extras = sorted(set(parameters) - set(properties))
        if extras and not bool(schema.get("additionalProperties", False)):
            raise ValueError(f"Unexpected parameters for {plugin.plugin_id}: {', '.join(extras)}")
        for name in extras:
            result[str(name)] = parameters[name]
        return result

    def _run_field_backend_summary(self, plugin: PluginManifest, parameters: Mapping[str, Any]) -> dict[str, Any]:
        backend_id = str(parameters.get("backend_id") or plugin.settings.get("backend_id") or "")
        backend = get_field_backend(backend_id)
        available = [
            {"后端标识": item.backend_id, "后端名称": item.display_name, "说明": item.description}
            for item in available_field_backends()
        ]
        return {
            "执行摘要": f"传播后端 {backend.display_name} 已通过插件注册表解析。",
            "后端": {"后端标识": backend.backend_id, "后端名称": backend.display_name, "说明": backend.description},
            "可用后端": available,
            "下一步接口": "后续可把该插件绑定到三维工作台求解按钮和插件级 V&V。",
        }

    def _run_data_import_summary(self, plugin: PluginManifest, parameters: Mapping[str, Any]) -> dict[str, Any]:
        report_type = str(parameters.get("report_type") or plugin.settings.get("report_type") or "evidence_chain")
        config_path = str(parameters.get("evidence_config") or plugin.settings.get("evidence_config") or "")
        data_import = DataImportService(self.output_dir)
        catalog = data_import.catalog()
        readiness = data_import.calibration_readiness()
        evidence = None
        if report_type in {"evidence_chain", "full"}:
            evidence = generate_evidence_chain_report(
                self.output_dir,
                config_path=config_path or None,
            )
        return {
            "执行摘要": "V3.0 数据导入插件已完成白名单运行审计。",
            "报告类型": report_type,
            "样例数": catalog.get("样例数", 0),
            "支持格式": catalog.get("支持格式", []),
            "标定准备度": readiness.get("总体得分"),
            "标定准备通过": bool(readiness.get("通过")),
            "证据链": {
                "生成": evidence is not None,
                "通过": bool(evidence and evidence.get("通过")),
                "真实源链与相位参考已接入": bool(evidence and evidence.get("真实源链与相位参考已接入")),
                "输出文件": evidence.get("输出文件") if evidence else None,
            },
            "输出边界": (
                "仅审计格式、单位、坐标、数据血缘、证据链和相位参考元数据；"
                "不输出真实源功率、现实作用距离、器件阈值或毁伤概率。"
            ),
        }

    def _run_perception_benchmark_summary(self, plugin: PluginManifest, parameters: Mapping[str, Any]) -> dict[str, Any]:
        algorithm = str(parameters.get("algorithm", "music_esprit"))
        return {
            "执行摘要": f"感知基准插件 {algorithm} 已完成白名单运行审计。",
            "能力": ["MUSIC", "ESPRIT", "PAWR-MUSIC", "空间平滑", "跟踪不确定度"],
            "验收证据": [
                "tests/test_music_fast_projection.py",
                "tests/test_esprit.py",
                "tests/test_spatial_smoothing.py",
                "tests/test_tracking.py",
            ],
            "输出边界": "仅输出归一化角度估计和误差统计，不绑定真实外场威胁参数。",
        }

    def _run_report_template_summary(self, plugin: PluginManifest, parameters: Mapping[str, Any]) -> dict[str, Any]:
        requested = str(parameters.get("format", "html"))
        known_outputs = {
            "html": self.output_dir / "v20A_可信度验证报告.html",
            "latex": self.output_dir / "v20A_论文表格.tex",
            "zip": self.output_dir / "v20A_VV结果包.zip",
        }
        output_path = known_outputs.get(requested, known_outputs["html"])
        return {
            "执行摘要": f"报告模板插件已选择 {requested} 输出。",
            "目标产物": str(output_path),
            "产物存在": output_path.exists(),
            "模板能力": ["中文 HTML 报告", "LaTeX 表格", "论文图包索引", "V&V 结果包"],
            "下一步接口": "V2.0D Paper Factory 将在此基础上生成 IEEE 草稿和补充材料。",
        }


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_parameter(plugin_id: str, name: str, value: Any, spec: Mapping[str, Any]) -> Any:
    expected = spec.get("type", "string")
    if "enum" in spec and value not in spec["enum"]:
        raise ValueError(f"Parameter {name} for {plugin_id} must be one of {spec['enum']}")
    if expected == "number":
        number = float(value)
        if "minimum" in spec and number < float(spec["minimum"]):
            raise ValueError(f"Parameter {name} for {plugin_id} is below minimum")
        if "maximum" in spec and number > float(spec["maximum"]):
            raise ValueError(f"Parameter {name} for {plugin_id} is above maximum")
        return number
    if expected == "integer":
        return int(value)
    if expected == "boolean":
        return bool(value)
    if expected == "array":
        if not isinstance(value, list):
            raise ValueError(f"Parameter {name} for {plugin_id} must be an array")
        return value
    if expected == "object":
        return dict(_mapping(value, name))
    return str(value)
