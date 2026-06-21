from pathlib import Path

from fastapi.testclient import TestClient

from hpm_platform.data_import import (
    DataImportService,
    generate_calibration_bridge_report,
    generate_external_data_vv_audit,
    generate_model_comparison_report,
    inspect_dataset,
)
from hpm_platform.ui.app_v20a import create_app


ROOT = Path(__file__).resolve().parents[1]


def test_v30_data_import_catalog_parses_builtin_samples(tmp_path):
    service = DataImportService(tmp_path)
    catalog = service.catalog()
    acceptance = catalog["验收"]

    assert catalog["版本"] == "V3.0-preview"
    assert {"CSV", "Touchstone", "NPZ", "HDF5", "CST", "HFSS", "MeasurementCampaign"} <= set(catalog["支持格式"])
    assert catalog["样例数"] == 7
    assert acceptance["通过"] is True
    assert {"CSV", "Touchstone", "NPZ", "HDF5", "CST", "HFSS", "MeasurementCampaign"} <= set(acceptance["已解析格式"])


def test_v30_data_import_inspects_csv_touchstone_npz_and_hdf5_stub(tmp_path):
    service = DataImportService(tmp_path)

    csv_payload = service.inspect_sample("V30-CSV-NEAR-FIELD")
    assert csv_payload["格式"] == "CSV"
    assert csv_payload["记录数"] == 6
    assert "x_lambda" in csv_payload["坐标列"]
    assert csv_payload["参数"]["复数字段"]

    s2p_payload = service.inspect_sample("V30-TOUCHSTONE-S2P")
    assert s2p_payload["格式"] == "Touchstone"
    assert s2p_payload["端口数"] == 2
    assert s2p_payload["频点数"] == 3
    assert s2p_payload["参数"]["reference_ohm"] == 50.0

    npz_payload = service.inspect_sample("V30-NPZ-FIELD")
    assert npz_payload["格式"] == "NPZ"
    assert any(item["名称"] == "normalized_field" and item["是否复数"] for item in npz_payload["数组"])

    h5_payload = service.inspect_sample("V30-HDF5-STUB")
    assert h5_payload["格式"] == "HDF5"
    assert h5_payload["参数"]["signature_valid"] is True

    cst_payload = service.inspect_sample("V30-CST-EXPORT")
    assert cst_payload["格式"] == "CST"
    assert cst_payload["参数"]["tool"] == "CST Studio Suite"
    assert cst_payload["参数"]["recognized_artifact_count"] >= 2
    assert "mm" in cst_payload["单位"]
    assert any(item["类型"] == "S参数" for item in cst_payload["数组"])

    hfss_payload = service.inspect_sample("V30-HFSS-EXPORT")
    assert hfss_payload["格式"] == "HFSS"
    assert "HFSS" in hfss_payload["参数"]["tool"]
    assert hfss_payload["参数"]["recognized_artifact_count"] >= 2
    assert "GHz" in hfss_payload["单位"]
    assert any(item["类型"] == "场数据" for item in hfss_payload["数组"])

    measurement_payload = service.inspect_sample("V30-MEASUREMENT-CAMPAIGN")
    assert measurement_payload["格式"] == "MeasurementCampaign"
    assert measurement_payload["参数"]["source_type"] == "measurement"
    assert measurement_payload["参数"]["batch_count"] == 2
    assert measurement_payload["参数"]["uncertainty_model"]["amplitude_sigma_norm"] == 0.025
    assert measurement_payload["参数"]["calibration"]["status"] == "preview-calibrated"
    assert measurement_payload["参数"]["instrument_chain"]


def test_v30_data_import_calibration_readiness_normalizes_measurement_campaign(tmp_path):
    service = DataImportService(tmp_path)
    readiness = service.calibration_readiness()

    assert readiness["通过"] is True
    assert readiness["总体得分"] > 50
    measurement = next(item for item in readiness["样例"] if item["样例ID"] == "V30-MEASUREMENT-CAMPAIGN")
    preview = measurement["规范化预览"]

    assert measurement["坐标规范化"] is True
    assert measurement["复场可用于标定"] is True
    assert measurement["不确定度可用"] is True
    assert measurement["校准状态可用"] is True
    assert preview["目标坐标"] == "lambda"
    assert preview["参考频率GHz"] == 3.0
    assert preview["复场样本数"] == 5
    assert preview["坐标预览"][0]["x_lambda"] < 0


def test_v30_data_import_calibration_bridge_builds_samples_and_report(tmp_path):
    service = DataImportService(tmp_path)
    report = generate_calibration_bridge_report(
        ROOT / "configs" / "cae_project_v14.yaml",
        tmp_path,
        service,
    )

    assert report["通过"] is True
    assert report["CalibrationSamples兼容"] is True
    assert report["样例ID"] == "V30-MEASUREMENT-CAMPAIGN"
    assert report["样本数"] == 5
    assert report["坐标来源单位"] == "mm"
    assert report["目标坐标"] == "lambda"
    assert report["参考频率GHz"] == 3.0
    assert report["规范化预览"][0]["x_lambda"] < 0
    assert report["标定预览"]["执行"] is True
    assert "代理激励" in report["代理激励"]
    assert report["阻断项"] == []
    assert Path(report["输出文件"]).exists()


def test_v30_data_import_model_comparison_reports_residuals_and_uncertainty(tmp_path):
    service = DataImportService(tmp_path)
    report = generate_model_comparison_report(
        ROOT / "configs" / "cae_project_v14.yaml",
        tmp_path,
        service,
    )

    assert report["通过"] is True
    assert report["样例ID"] == "V30-MEASUREMENT-CAMPAIGN"
    assert report["样本数"] == 5
    assert report["误差对比"]["求解成功"] is True
    assert report["误差对比"]["标定后相对RMSE/%"] > 0
    assert report["不确定度覆盖率"]["不确定度可用"] is True
    assert report["不确定度覆盖率"]["2sigma覆盖率/%"] >= 0
    assert len(report["逐点残差"]) == 5
    assert "合成sigma" in report["逐点残差"][0]
    assert any(item["项目"] == "真实源链与相位参考已接入" and item["通过"] is False for item in report["门槛"])
    assert "代理激励" in report["安全边界"]
    assert Path(report["输出文件"]).exists()


def test_v30_external_data_vv_audit_keeps_proxy_data_out_of_formal_score(tmp_path):
    service = DataImportService(tmp_path)
    report = generate_external_data_vv_audit(
        ROOT / "configs" / "cae_project_v14.yaml",
        tmp_path,
        service,
        base_credibility_score=91.58,
    )

    assert report["通过"] is False
    assert report["可纳入正式可信度评分"] is False
    assert report["样本数"] == 5
    assert 0 <= report["预评分"] < 60
    assert report["正式评分策略"]["风险调整预览评分"] == 91.58
    assert report["正式评分策略"]["是否改写正式评分"] is False
    assert any("真实源链" in item for item in report["风险信号"])
    assert any(item["项目"] == "真实源链与相位参考已接入" and item["通过"] is False for item in report["门槛"])
    assert Path(report["输出文件"]).exists()


def test_v30_data_import_rejects_unknown_format(tmp_path):
    path = tmp_path / "unknown.dat"
    path.write_text("not a supported format", encoding="utf-8")

    try:
        inspect_dataset(path)
    except ValueError as exc:
        assert "暂不支持" in str(exc)
    else:
        raise AssertionError("unknown format should be rejected")


def test_v30_data_import_api_and_frontend_assets(tmp_path):
    with TestClient(create_app(ROOT / "configs" / "cae_project_v14.yaml", tmp_path)) as client:
        catalog = client.get("/api/data-import/catalog")
        acceptance = client.get("/api/data-import/acceptance")
        readiness = client.get("/api/data-import/calibration-readiness")
        bridge = client.get("/api/data-import/calibration-bridge")
        model_comparison = client.get("/api/data-import/model-comparison")
        vv_audit = client.get("/api/data-import/vv-audit")
        sample = client.get("/api/data-import/samples/V30-TOUCHSTONE-S2P")
        by_path = client.post("/api/data-import/inspect", json={"path": sample.json()["源文件"]})

    assert catalog.status_code == 200
    assert catalog.json()["样例数"] == 7
    assert acceptance.status_code == 200
    assert acceptance.json()["通过"] is True
    assert readiness.status_code == 200
    assert readiness.json()["通过"] is True
    assert any(item["样例ID"] == "V30-MEASUREMENT-CAMPAIGN" for item in readiness.json()["样例"])
    assert bridge.status_code == 200
    assert bridge.json()["通过"] is True
    assert bridge.json()["CalibrationSamples兼容"] is True
    assert bridge.json()["样本数"] == 5
    assert model_comparison.status_code == 200
    assert model_comparison.json()["通过"] is True
    assert model_comparison.json()["样本数"] == 5
    assert model_comparison.json()["不确定度覆盖率"]["不确定度可用"] is True
    assert vv_audit.status_code == 200
    assert vv_audit.json()["可纳入正式可信度评分"] is False
    assert vv_audit.json()["样本数"] == 5
    assert sample.status_code == 200
    assert sample.json()["格式"] == "Touchstone"
    assert by_path.status_code == 200
    assert by_path.json()["SHA256"] == sample.json()["SHA256"]

    html = (ROOT / "src" / "hpm_platform" / "ui" / "templates_v20a" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "src" / "hpm_platform" / "ui" / "static_v20a" / "js" / "v20a.js").read_text(encoding="utf-8")
    assert 'data-testid="nav-data-import"' in html
    assert 'data-testid="data-import-samples"' in html
    assert 'data-testid="data-import-calibration-readiness"' in html
    assert 'data-testid="data-import-calibration-bridge"' in html
    assert 'data-testid="data-import-model-comparison"' in html
    assert 'data-testid="data-import-vv-audit"' in html
    assert "/api/data-import/catalog" in js
    assert "/api/data-import/calibration-bridge" in js
    assert "/api/data-import/model-comparison" in js
    assert "/api/data-import/vv-audit" in js
    assert "渲染数据导入标定准备" in js
    assert "渲染数据导入标定桥接" in js
    assert "渲染数据导入模型误差对比" in js
    assert "渲染数据导入VV审计" in js
    assert "/api/data-import/inspect" in js
