from app.services.device_service import DeviceService


def test_nvme_details_queries_are_limited_and_combined(monkeypatch):
    monkeypatch.setattr("app.services.device_service.shutil.which", lambda _: "/usr/bin/nvme")
    calls = []

    def fake_command(command, timeout=15):
        calls.append((command, timeout))
        if command[1] == "id-ctrl":
            return {"fr": "1.23"}
        return {"temperature": 306}

    monkeypatch.setattr(DeviceService, "_command_json", staticmethod(fake_command))
    details = DeviceService._nvme_details_for_paths(["/dev/nvme0n1", "/dev/nvme1n1"])

    assert details == {"/dev/nvme0n1": ("1.23", 32.85000000000002), "/dev/nvme1n1": ("1.23", 32.85000000000002)}
    assert len(calls) == 4
    assert {timeout for _, timeout in calls} == {3}
