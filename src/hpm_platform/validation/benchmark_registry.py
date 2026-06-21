"""V2.0A V&V 基准注册表。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from hpm_platform.validation.analytic_cases import (
    CaseResult,
    run_array_factor_case,
    run_backend_consistency_case,
    run_green_function_case,
    run_music_esprit_case,
    run_mvdr_lcmv_case,
    run_scan_beam_case,
)


@dataclass(frozen=True)
class BenchmarkSpec:
    case_id: str
    name: str
    category: str
    config_file: str
    runner: Callable[[], CaseResult]


def benchmark_registry() -> tuple[BenchmarkSpec, ...]:
    return (
        BenchmarkSpec("VV-01", "8x8均匀矩形阵列远场方向图解析验证", "解析解验证", "configs/vv/analytic_array_factor.yaml", run_array_factor_case),
        BenchmarkSpec("VV-02", "相位扫描波束指向解析验证", "解析解验证", "configs/vv/analytic_array_factor.yaml", run_scan_beam_case),
        BenchmarkSpec("VV-03", "自由空间Green函数幅相验证", "解析解验证", "configs/vv/free_space_green.yaml", run_green_function_case),
        BenchmarkSpec("VV-04", "MUSIC/ESPRIT/PAWR测向基准验证", "算法基准验证", "configs/vv/music_benchmark.yaml", run_music_esprit_case),
        BenchmarkSpec("VV-05", "MVDR/LCMV约束响应验证", "算法基准验证", "configs/vv/mvdr_benchmark.yaml", run_mvdr_lcmv_case),
        BenchmarkSpec("VV-06", "传播后端一致性与适用性验证", "后端一致性验证", "configs/vv/field_backend_validation.yaml", run_backend_consistency_case),
    )


def registry_as_dict() -> list[dict[str, str]]:
    return [
        {
            "用例编号": item.case_id,
            "用例名称": item.name,
            "类别": item.category,
            "配置文件": item.config_file,
        }
        for item in benchmark_registry()
    ]
