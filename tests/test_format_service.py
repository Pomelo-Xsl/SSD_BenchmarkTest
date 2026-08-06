from app.services.format_service import NvmeFormatService


def test_nvme_format_command_uses_fixed_safe_parameters():
    assert NvmeFormatService.build_command("/dev/nvme1n1") == [
        "nvme", "format", "/dev/nvme1n1", "-s", "0", "-l", "0", "-i", "0",
        "-p", "0", "-m", "1", "-f",
    ]
