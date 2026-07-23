# NVMe SSD Benchmark MVP

基于 FastAPI、SQLite、fio 和 nvme-cli 的精简 NVMe SSD 测试工具，仅提供设备扫描、测试执行和结果查询。

> 警告：fio 的写入测试会覆盖目标设备上的数据。平台仅允许对未挂载、非系统 NVMe 设备执行，并且写任务必须在 API 中显式确认。

## 安装与启动

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Linux 主机还需安装 `fio`、`nvme-cli` 和 `lsblk`（通常来自 util-linux）；执行实际测试的服务进程需要 root 权限。可复制 `configs/settings.example.env` 为 `.env` 修改数据库、结果目录和时长。

启动后访问 `/` 即可进入中文图形操作界面；`/docs` 保留给需要直接调用 API 的用户。

## API

- `GET /health`：服务健康状态。
- `GET /api/devices`：扫描并保存 NVMe 设备信息。
- `POST /api/tests`：创建并后台执行测试。
- `GET /api/results/{task_id}`：查询测试状态；完成时返回指标。

创建只读任务示例：

```bash
curl -X POST http://127.0.0.1:8000/api/tests \
  -H 'content-type: application/json' \
  -d '{"test_name":"rand_read_4k"}'
```

默认测试盘由 `.env` 中的 `SSD_BENCHMARK_DEFAULT_DEVICE_NAME` 配置，当前为 `nvme1n1`。创建写任务时必须加上 `"confirm_destructive": true`。支持 `seq_read_128k`、`seq_write_128k`、`rand_read_4k`、`rand_write_4k`。默认 io_uring、direct=1、runtime=60 秒、ramp=10 秒。

可在每个请求的 `fio_options` 中传递任意 fio 参数，例如：

```json
{
  "device_name": "nvme1n1",
  "test_name": "rand_read_4k",
  "fio_options": {
    "runtime_seconds": 60,
    "ramp_time_seconds": 10,
    "iodepth": 32,
    "numjobs": 1,
    "ioengine": "io_uring",
    "direct": true,
    "bs": "16k",
    "norandommap": true,
    "rwmixread": 70
  }
}
```

常用字段会在 Swagger 中提示，也可以追加任意 fio 参数（如 `bs`、`rw`、`size`、`offset`、`norandommap`），包括任意 fio 支持的 I/O 引擎。为保证设备安全和结果可解析，`filename`、`name`、`output`、`output-format`、`time_based` 及执行外部命令的参数不能覆盖。自定义 `rw` 为非 `read` / `randread` 时，必须将 `confirm_destructive` 设为 `true`。

fio 原始 JSON 写入 `results/`，运行日志写入 `logs/app.log`、`logs/fio.log` 和 `logs/error.log`。数据库默认 `benchmark.db`。

设备扫描结果中的 `safe_to_test` 为 `true` 才可创建测试；`mounted`、`system_disk`、`has_partitions` 和 `safety_message` 会说明拒绝原因。
