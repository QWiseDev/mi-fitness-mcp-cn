"""云端最新状态：全局游标 + 最新运动记录 + 本地各类型数据新鲜度。"""

import json
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
from mi_fitness_mcp.storage import Database


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


def _local_freshness(db: Database, user_id: str) -> dict[str, dict[str, Any]]:
    """本地各类型最新记录时间；时间戳类型附 age_hours（相对 UTC now）。"""
    freshness: dict[str, dict[str, Any]] = {}
    now = datetime.now(UTC)
    for data_type, latest in db.get_data_freshness(user_id).items():
        if not latest:
            freshness[data_type] = {"latest": None}
            continue
        if data_type == "daily_activity":
            # 日期粒度（当天活动），不折算时长
            freshness[data_type] = {"latest_date": latest}
            continue
        entry: dict[str, Any] = {"latest": latest}
        with suppress(ValueError):
            moment = datetime.fromisoformat(latest)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
            entry["age_hours"] = round((now - moment).total_seconds() / 3600, 1)
        freshness[data_type] = entry
    return freshness


async def get_latest_data(
    adapter: MiFitnessCloudAdapter, db: Database, user_id: str
) -> dict[str, Any]:
    """云端游标 + 最新运动记录 + 本地各类型新鲜度；游标未变即无新数据。"""
    cloud_watermark = await adapter.get_max_watermark()
    latest_workout = None
    record = await adapter.get_latest_sport_record()
    if record:
        latest_workout = _parse_sport_record(record)
    return {
        "cloud_watermark": cloud_watermark,
        "latest_workout": latest_workout,
        "freshness": _local_freshness(db, user_id),
    }
