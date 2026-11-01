"""运动详情：云端记录内嵌的 value 摘要 + 本地心率样本合并。

小米云的运动列表接口（get_sport_records_by_time）每条记录的 value 字段
即 App 详情页数据（训练效果、心率区间、训练负荷等），无需单独的详情接口；
轨迹/分段云端未在本仓库验证过，暂不包含。
"""

import json
from contextlib import suppress
from datetime import datetime
from typing import Any

from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
from mi_fitness_mcp.storage import Database


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(str(value))


async def get_workout_detail(
    adapter: MiFitnessCloudAdapter | None,
    db: Database,
    user_id: str,
    workout_id: str,
) -> dict[str, Any]:
    """合并本地运动记录、云端 value 摘要与运动期间心率样本。

    workout_id 为本地库主键（{sid}_{key}_{time}）；云端摘要按记录的
    time 字段（本地 source_record_id）在运动当日窗口内回查。
    """
    workout = db.get_workout_by_id(user_id, workout_id)
    if workout is None:
        raise ValueError(f"未找到运动记录: {workout_id}")

    start_at = _parse_ts(workout["start_at"])
    end_at = _parse_ts(workout["end_at"])
    detail: dict[str, Any] = {
        "workout_id": workout_id,
        "activity_type": workout["activity_type"],
        "start_at": workout["start_at"],
        "end_at": workout["end_at"],
        "duration_minutes": workout["duration_minutes"],
        "distance_m": workout["distance_m"],
        "calories_kcal": workout["calories_kcal"],
        "avg_heart_rate_bpm": workout["avg_heart_rate_bpm"],
        "max_heart_rate_bpm": workout["max_heart_rate_bpm"],
        "avg_pace_sec_per_km": workout["avg_pace_sec_per_km"],
        "total_steps": workout["total_steps"],
    }

    # 云端摘要：适配器离线或云端已查不到该记录时保持 None，详情仍可用
    cloud_summary = None
    if adapter is not None and adapter.is_connected():
        record_time = workout["source_record_id"] or workout_id.rsplit("_", 1)[-1]
        records = await adapter._fetch_sport_records_by_time(
            start_at.date().isoformat(), end_at.date().isoformat()
        )
        raw = next(
            (r for r in records if str(r.get("time")) == str(record_time)),
            None,
        )
        if raw is not None:
            with suppress(json.JSONDecodeError, TypeError):
                cloud_summary = json.loads(raw["value"])
    detail["cloud_summary"] = cloud_summary

    detail["heart_rate_samples"] = [
        {"timestamp": row["timestamp"], "bpm": row["bpm"]}
        for row in db.query_heart_rate_samples(
            user_id, start_at.date().isoformat(), end_at.date().isoformat()
        )
        if row.get("sample_type") == "workout" and start_at <= _parse_ts(row["timestamp"]) <= end_at
    ]
    return detail
