import json
from app.parsers.fio_parser import FioParser


def test_parse_read_result(tmp_path):
    report = {"jobs": [{"read": {"io_bytes": 1, "iops": 2000, "bw_bytes": 104857600, "lat_ns": {"mean": 8000, "percentile": {"99.000000": 30000}}}, "write": {}, "usr_cpu": 2.5, "sys_cpu": 1.0}]}
    path = tmp_path / "fio.json"
    path.write_text(json.dumps(report))
    result = FioParser.parse(path)
    assert result.iops == 2000
    assert result.bw_mib_s == 100
    assert result.latency_avg_us == 8
    assert result.latency_p99_us == 30
