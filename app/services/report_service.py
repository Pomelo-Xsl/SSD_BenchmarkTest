"""生成 JSON、CSV、Markdown 和 HTML 格式的测试分析报告。"""
from __future__ import annotations
import csv
import html
import io
import json
from datetime import datetime
from typing import Any
from app.analytics.types import serialise


class ReportService:
    MIME_TYPES = {"json": "application/json", "csv": "text/csv; charset=utf-8", "markdown": "text/markdown; charset=utf-8", "html": "text/html; charset=utf-8"}

    @classmethod
    def render(cls, payload: dict[str, Any], report_format: str) -> tuple[str, str]:
        if report_format == "json":
            return json.dumps(serialise(payload), ensure_ascii=False, indent=2), cls.MIME_TYPES[report_format]
        if report_format == "csv":
            return cls.csv(payload), cls.MIME_TYPES[report_format]
        if report_format == "markdown":
            return cls.markdown(payload), cls.MIME_TYPES[report_format]
        if report_format == "html":
            return cls.html(payload), cls.MIME_TYPES[report_format]
        raise ValueError("报告格式仅支持 json、csv、markdown、html")

    @staticmethod
    def csv(payload: dict[str, Any]) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["类别", "指标", "数值", "说明"])
        for key, value in payload.get("analysis", {}).get("metrics", {}).items():
            writer.writerow(["性能", key, value, ""])
        score = payload.get("analysis", {}).get("scorecard", {})
        writer.writerow(["评分", "total", score.get("total"), score.get("summary", "")])
        for item in score.get("dimensions", []):
            writer.writerow(["评分维度", item.get("title"), item.get("score"), item.get("explanation")])
        for item in payload.get("analysis", {}).get("anomalies", []):
            writer.writerow(["异常", item.get("title"), item.get("observed"), item.get("detail")])
        quality = payload.get("analysis", {}).get("quality") or {}
        writer.writerow(["数据质量", "score", quality.get("score"), quality.get("summary", "")])
        for item in quality.get("checks", []):
            writer.writerow(["数据质量检查", item.get("title"), item.get("status"), item.get("detail")])
        for item in payload.get("analysis", {}).get("forecasts", []):
            writer.writerow(["趋势预测", item.get("metric"), item.get("next_value"), item.get("message")])
        for item in payload.get("analysis", {}).get("recommendations", []):
            writer.writerow(["操作建议", item.get("title"), item.get("priority"), "；".join(item.get("actions", []))])
        return output.getvalue()

    @staticmethod
    def markdown(payload: dict[str, Any]) -> str:
        task = payload.get("task", {})
        analysis = payload.get("analysis", {})
        rows = [f"# SSD BenchmarkTest 报告：任务 #{task.get('id')}", "", f"- 设备：{task.get('device_name')}", f"- 测试：{task.get('test_name')}", f"- 状态：{task.get('status')}", "", "## 性能指标", "", "| 指标 | 数值 |", "|---|---:|"]
        rows += [f"| {key} | {value} |" for key, value in analysis.get("metrics", {}).items()]
        score = analysis.get("scorecard", {})
        rows += ["", "## 综合评分", "", f"**{score.get('total', '—')} / 100**，等级 **{score.get('grade', '—')}**。", "", score.get("summary", "")]
        anomalies = analysis.get("anomalies", [])
        rows += ["", "## 异常提示", ""]
        rows += [f"- {item.get('title')}：{item.get('detail')}" for item in anomalies] or ["- 未发现明显异常。"]
        quality = analysis.get("quality") or {}
        rows += ["", "## 数据质量", "", f"质量分：**{quality.get('score', '—')} / 100**；{quality.get('summary', '暂无质量结论')}"]
        rows += [f"- {item.get('title')}：{item.get('detail')}" for item in quality.get("checks", []) if item.get("status") != "pass"]
        forecasts = analysis.get("forecasts", [])
        rows += ["", "## 趋势预测", ""]
        rows += [f"- {item.get('metric')}：下一轮预测 {item.get('next_value')}；{item.get('message')}" for item in forecasts] or ["- 历史样本不足，暂无趋势预测。"]
        rows += ["", "## 操作建议", ""]
        for item in analysis.get("recommendations", []):
            rows.append(f"- **{item.get('title')}**：{item.get('rationale')}")
            rows.extend([f"  - {action}" for action in item.get("actions", [])])
        return "\n".join(rows)

    @classmethod
    def html(cls, payload: dict[str, Any]) -> str:
        markdown = cls.markdown(payload)
        escaped = html.escape(markdown)
        return f"<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>SSD BenchmarkTest 报告</title><style>body{{font:14px/1.6 system-ui;margin:40px;max-width:960px}}pre{{white-space:pre-wrap;background:#f5f7fb;padding:20px;border-radius:10px}}</style><body><pre>{escaped}</pre><footer>生成时间：{datetime.now().isoformat()}</footer></body></html>"
