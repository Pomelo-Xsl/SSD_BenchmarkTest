import json

from app.services.report_service import ReportService


PAYLOAD = {"task": {"id": 1, "device_name": "nvme1n1", "test_name": "rand_read_4k", "status": "completed"}, "analysis": {"metrics": {"iops": 1000}, "scorecard": {"total": 80, "grade": "B", "summary": "ok", "dimensions": []}, "anomalies": []}}


def test_report_service_supports_all_export_formats():
    for report_format in ("json", "csv", "markdown", "html"):
        body, media_type = ReportService.render(PAYLOAD, report_format)
        assert body
        assert media_type
    assert json.loads(ReportService.render(PAYLOAD, "json")[0])["task"]["id"] == 1


def test_report_service_rejects_unknown_format():
    try:
        ReportService.render(PAYLOAD, "pdf")
    except ValueError as exc:
        assert "json" in str(exc)
    else:
        raise AssertionError("unknown format should fail")
