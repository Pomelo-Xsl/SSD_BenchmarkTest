"""多粒度混合读写 fio 负载定义、验证和命令构建。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Iterable

@dataclass(frozen=True)
class WorkloadPhase:
    name: str
    duration_seconds: int
    block_size: str
    read_percent: int
    random_percent: int
    iodepth: int
    numjobs: int
    direct: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def write_percent(self) -> int:
        return 100 - self.read_percent

    @property
    def fio_rw(self) -> str:
        if self.random_percent == 100:
            return "randrw"
        if self.random_percent == 0:
            return "rw"
        return "randrw"

    def as_fio_options(self) -> dict[str, Any]:
        options = {"rw": self.fio_rw, "rwmixread": self.read_percent, "bs": self.block_size, "iodepth": self.iodepth, "numjobs": self.numjobs, "runtime": self.duration_seconds, "time_based": 1, "direct": int(self.direct)}
        if self.random_percent not in {0, 100}:
            options["percentage_random"] = self.random_percent
        return options | self.extra

@dataclass(frozen=True)
class MixedWorkload:
    name: str
    description: str
    phases: tuple[WorkloadPhase, ...]
    destructive: bool

    @property
    def total_seconds(self) -> int:
        return sum(item.duration_seconds for item in self.phases)

    def profile(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "destructive": self.destructive, "total_seconds": self.total_seconds, "phases": [phase.as_fio_options() | {"name": phase.name, "write_percent": phase.write_percent} for phase in self.phases]}

class MixedWorkloadService:
    PRESETS = {
        "database_oltp": {"description": "4K 随机混合读写，模拟在线交易型数据库。", "phases": [{"name":"steady","duration_seconds":600,"block_size":"4k","read_percent":70,"random_percent":100,"iodepth":32,"numjobs":4}]},
        "virtualization": {"description": "多块大小的随机混合 I/O，模拟虚拟机宿主机。", "phases": [{"name":"small_io","duration_seconds":300,"block_size":"4k","read_percent":60,"random_percent":100,"iodepth":64,"numjobs":4},{"name":"medium_io","duration_seconds":300,"block_size":"16k","read_percent":70,"random_percent":80,"iodepth":32,"numjobs":2}]},
        "web_service": {"description": "以读取为主的随机访问负载。", "phases": [{"name":"read_heavy","duration_seconds":300,"block_size":"8k","read_percent":90,"random_percent":90,"iodepth":32,"numjobs":2}]},
        "write_stress": {"description": "高写入比例耐久压力负载，具有破坏性。", "phases": [{"name":"precondition","duration_seconds":600,"block_size":"128k","read_percent":0,"random_percent":0,"iodepth":32,"numjobs":1},{"name":"mixed_write","duration_seconds":1800,"block_size":"4k","read_percent":20,"random_percent":100,"iodepth":64,"numjobs":4}]},
    }

    @classmethod
    def presets(cls) -> list[dict[str, Any]]:
        return [{"key": key, **value} for key, value in cls.PRESETS.items()]

    @staticmethod
    def _number(payload: dict[str, Any], key: str, lower: int, upper: int) -> int:
        value = int(payload.get(key))
        if not lower <= value <= upper:
            raise ValueError(f"{key} 必须为 {lower} 到 {upper}")
        return value

    @classmethod
    def phase(cls, payload: dict[str, Any], index: int = 1) -> WorkloadPhase:
        try:
            name = str(payload.get("name") or f"phase_{index}").strip()
            if not name:
                raise ValueError("阶段名称不能为空")
            block_size = str(payload["block_size"]).strip().lower()
            if not block_size or len(block_size) > 16:
                raise ValueError("block_size 无效")
            duration = cls._number(payload, "duration_seconds", 1, 86400)
            read = cls._number(payload, "read_percent", 0, 100)
            random = cls._number(payload, "random_percent", 0, 100)
            depth = cls._number(payload, "iodepth", 1, 1024)
            jobs = cls._number(payload, "numjobs", 1, 128)
        except KeyError as exc:
            raise ValueError(f"缺少阶段参数：{exc.args[0]}") from exc
        extra = dict(payload.get("extra") or {})
        forbidden = {"filename", "name", "output", "output-format", "rw", "rwmixread", "runtime"}
        conflict = forbidden & set(extra)
        if conflict:
            raise ValueError("extra 参数不允许覆盖受控字段：" + "、".join(sorted(conflict)))
        return WorkloadPhase(name, duration, block_size, read, random, depth, jobs, bool(payload.get("direct", True)), extra)

    @classmethod
    def create(cls, name: str, description: str, phases: Iterable[dict[str, Any]]) -> MixedWorkload:
        parsed = tuple(cls.phase(item, index + 1) for index, item in enumerate(phases))
        if not parsed:
            raise ValueError("至少需要一个负载阶段")
        if len(parsed) > 16:
            raise ValueError("最多支持 16 个负载阶段")
        duplicate = len({item.name for item in parsed}) != len(parsed)
        if duplicate:
            raise ValueError("负载阶段名称不可重复")
        destructive = any(item.write_percent > 0 for item in parsed)
        return MixedWorkload(name.strip() or "mixed_workload", description.strip(), parsed, destructive)

    @classmethod
    def from_preset(cls, key: str, overrides: dict[str, Any] | None = None) -> MixedWorkload:
        if key not in cls.PRESETS:
            raise ValueError("未知混合负载预设")
        source = cls.PRESETS[key]
        phases = [dict(item) for item in source["phases"]]
        if overrides:
            for phase in phases:
                phase.update(overrides)
        return cls.create(key, source["description"], phases)

    @staticmethod
    def fio_job_sections(workload: MixedWorkload, device_path: str, ioengine: str = "io_uring") -> str:
        """生成可独立复核的 fio job 文件文本；不直接执行。"""
        common = ["[global]", f"filename={device_path}", f"ioengine={ioengine}", "group_reporting=1", "thread=1", "invalidate=1"]
        sections = ["\n".join(common)]
        for phase in workload.phases:
            options = phase.as_fio_options()
            lines = [f"[{phase.name}]"]
            lines.extend(f"{key}={str(value).lower() if isinstance(value,bool) else value}" for key, value in options.items())
            sections.append("\n".join(lines))
        return "\n\n".join(sections) + "\n"

    @staticmethod
    def expected_write_ratio(workload: MixedWorkload) -> float:
        total = workload.total_seconds
        return 0.0 if total == 0 else round(sum(item.duration_seconds * item.write_percent for item in workload.phases) / total, 2)
