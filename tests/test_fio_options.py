from pathlib import Path
from app.services.fio_service import FioOptions, FioService


def test_build_command_uses_task_fio_options():
    options = FioOptions.from_mapping({
        "runtime_seconds": 15, "ramp_time_seconds": 2, "iodepth": 64,
        "numjobs": 4, "ioengine": "libaio", "direct": False,
    })
    command = FioService.build_command("/dev/nvme1n1", "rand_read_4k", Path("result.json"), options)
    assert "--runtime=15" in command
    assert "--ramp_time=2" in command
    assert "--iodepth=64" in command
    assert "--numjobs=4" in command
    assert "--ioengine=libaio" in command
    assert "--direct=0" in command


def test_build_command_accepts_arbitrary_fio_option():
    options = FioOptions.from_mapping({"bs": "16k", "norandommap": True, "rwmixread": 70})
    command = FioService.build_command("/dev/nvme1n1", "rand_read_4k", Path("result.json"), options)
    assert "--bs=16k" in command
    assert "--norandommap=1" in command
    assert "--rwmixread=70" in command


def test_protected_fio_options_are_rejected():
    try:
        FioOptions.from_mapping({"filename": "/tmp/other-device"})
    except ValueError as exc:
        assert "保护" in str(exc)
    else:
        raise AssertionError("受保护参数必须被拒绝")
