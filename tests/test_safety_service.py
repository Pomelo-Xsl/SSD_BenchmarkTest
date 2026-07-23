from app.services.safety_service import SafetyService


def test_inspect_nodes_reports_safe_empty_disk():
    nodes = [{"path": "/dev/nvme1n1", "type": "disk", "mountpoints": [None]}]
    result = SafetyService.inspect_nodes(nodes, "/dev/nvme1n1", "/dev/mapper/system")
    assert result.safe_to_test is True
    assert result.safety_message is None


def test_inspect_nodes_rejects_system_disk_and_partitions():
    nodes = [{"path": "/dev/nvme0n1", "type": "disk", "mountpoints": [None], "children": [
        {"path": "/dev/nvme0n1p1", "type": "part", "mountpoints": ["/"], "children": [
            {"path": "/dev/mapper/system", "type": "lvm", "mountpoints": ["/"]}
        ]}
    ]}]
    result = SafetyService.inspect_nodes(nodes, "/dev/nvme0n1", "/dev/mapper/system")
    assert result.mounted is True
    assert result.system_disk is True
    assert result.has_partitions is True
    assert result.safe_to_test is False
