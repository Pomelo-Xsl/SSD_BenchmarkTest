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


def test_parser_reads_p99_from_clat_ns_when_lat_ns_has_no_percentiles(tmp_path):
    report = {"jobs": [{"read": {"io_bytes": 1, "iops": 100, "bw_bytes": 1024, "lat_ns": {"mean": 8000}, "clat_ns": {"percentile": {"99.000000": 55000}}}, "write": {}, "usr_cpu": 1, "sys_cpu": 1}]}
    path = tmp_path / "fio-clat.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    result = FioParser.parse(path)
    assert result.latency_avg_us == 8
    assert result.latency_p99_us == 55
