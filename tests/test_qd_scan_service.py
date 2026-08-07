from app.services.qd_scan_service import QdScanService


def test_qd_scan_creates_a_dedicated_batch_type(monkeypatch):
    captured = {}

    def fake_create(db, device_name, tests, batch_type):
        captured["device_name"] = device_name
        captured["tests"] = tests
        captured["batch_type"] = batch_type
        return object(), []

    monkeypatch.setattr("app.services.qd_scan_service.BatchService.create", fake_create)
    plan = QdScanService.plan("nvme1n1", "rand_read_4k", [1, 8])
    QdScanService.create_batch(object(), plan, confirm_destructive=False)

    assert captured["batch_type"] == "qd_scan"
    assert [item["fio_options"]["iodepth"] for item in captured["tests"]] == [1, 8]
    assert all("qd_scan" not in item["fio_options"] for item in captured["tests"])
