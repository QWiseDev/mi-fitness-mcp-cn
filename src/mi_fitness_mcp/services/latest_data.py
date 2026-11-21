"""云端最新状态：全局游标 + 最新运动记录（value 摘要解析）。"""

import json
from contextlib import suppress
from typing import Any

from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter


def _parse_sport_record(record: dict) -> dict[str, Any]:
    """把云端原始 sport_record 压成摘要 + 完整 value 字段。"""
    value: dict[str, Any] = {}
    with suppress(json.JSONDecodeError, TypeError):
        value = json.loads(record.get("value") or "{}")

    start = record.get("time")
    start_at = None
    if start:
        start_at = MiFitnessCloudAdapter._timestamp_to_datetime(
            start, record.get("zone_offset") or 0
        ).isoformat()
    duration = value.get("duration")
    end_at = None
    if start and duration:
        end_at = MiFitnessCloudAdapter._timestamp_to_datetime(
            int(start) + int(duration), record.get("zone_offset") or 0
        ).isoformat()

    return {
        "sid": record.get("sid"),
        "activity_type": record.get("category") or record.get("key"),
        "start_at": start_at,
        "end_at": end_at,
        "duration_minutes": int(duration) // 60 if duration else None,
        "distance_m": value.get("distance"),
        "calories_kcal": value.get("calories") or value.get("total_cal"),
        "avg_heart_rate_bpm": value.get("avg_hrm"),
        "max_heart_rate_bpm": value.get("max_hrm"),
        "cloud_watermark": record.get("watermark"),
        "summary": value,
    }


async def get_latest_data(adapter: MiFitnessCloudAdapter) -> dict[str, Any]:
    """云端游标 + 最新运动记录；两者独立获取，互不影响。"""
    cloud_watermark = await adapter.get_max_watermark()
    latest_workout = None
    record = await adapter.get_latest_sport_record()
    if record:
        latest_workout = _parse_sport_record(record)
    return {"cloud_watermark": cloud_watermark, "latest_workout": latest_workout}
