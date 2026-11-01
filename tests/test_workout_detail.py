"""get_workout_detail 的单元测试：云端 value 摘要与本地心率样本合并。"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from mi_fitness_mcp.models import HeartRateSample, Workout
from mi_fitness_mcp.services.workout_detail import get_workout_detail
from mi_fitness_mcp.storage import Database

TZ = timezone(timedelta(hours=8))
USER = "u1"
WORKOUT_ID = "2239623568_indoor_walking_1793427743"

VALUE = json.dumps(
    {
        "train_effect": 3.33,
        "train_load": 84,
        "avg_hrm": 124,
        "max_hrm": 159,
        "hrm_fat_burning_duration": 2527,
        "calories": 726,
    }
)


class FakeAdapter:
    def __init__(self, records=None):
        self._records = records or []

    def is_connected(self):
        return True

    async def _fetch_sport_records_by_time(self, start_date, end_date):
        return self._records


def seed(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_workout(
        Workout(
            id=f"mi_fitness_workout_{WORKOUT_ID}",
            provider="mi_fitness",
            source_type="cloud_session",
            user_id=USER,
            source_record_id="1793427743",
            workout_id=WORKOUT_ID,
            activity_type="walking",
            start_at=datetime(2026, 10, 18, 10, 0, tzinfo=TZ),
            end_at=datetime(2026, 10, 18, 11, 0, tzinfo=TZ),
            duration_minutes=60,
        )
    )
    for record_id, hour, bpm, sample_type in (
        ("h1", "10:20", 110, "workout"),
        ("h2", "10:40", 130, "workout"),
        ("h3", "10:50", 95, "passive"),
    ):
        db.insert_heart_rate_sample(
            HeartRateSample(
                id=record_id,
                provider="mi_fitness",
                source_type="cloud_session",
                user_id=USER,
                timestamp=datetime.fromisoformat(f"2026-10-18T{hour}:00+08:00"),
                bpm=bpm,
                sample_type=sample_type,
            )
        )
    # 窗口外的 workout 样本，应被排除
    db.insert_heart_rate_sample(
        HeartRateSample(
            id="h4",
            provider="mi_fitness",
            source_type="cloud_session",
            user_id=USER,
            timestamp=datetime(2026, 10, 19, 10, 0, tzinfo=TZ),
            bpm=120,
            sample_type="workout",
        )
    )
    return db


async def test_detail_merges_cloud_summary_and_local_hr(tmp_path):
    db = seed(tmp_path)
    adapter = FakeAdapter([{"time": 1793427743, "value": VALUE}])

    detail = await get_workout_detail(adapter, db, USER, WORKOUT_ID)

    assert detail["activity_type"] == "walking"
    assert detail["duration_minutes"] == 60
    assert detail["cloud_summary"]["train_effect"] == 3.33
    assert detail["cloud_summary"]["hrm_fat_burning_duration"] == 2527
    assert [s["bpm"] for s in detail["heart_rate_samples"]] == [110, 130]


async def test_detail_works_without_cloud(tmp_path):
    db = seed(tmp_path)

    detail = await get_workout_detail(None, db, USER, WORKOUT_ID)

    assert detail["cloud_summary"] is None
    assert len(detail["heart_rate_samples"]) == 2


async def test_detail_missing_cloud_record_keeps_local_data(tmp_path):
    db = seed(tmp_path)
    adapter = FakeAdapter([{"time": 111, "value": VALUE}])

    detail = await get_workout_detail(adapter, db, USER, WORKOUT_ID)

    assert detail["cloud_summary"] is None
    assert len(detail["heart_rate_samples"]) == 2


async def test_detail_unknown_workout_raises(tmp_path):
    db = seed(tmp_path)

    with pytest.raises(ValueError, match="未找到运动记录"):
        await get_workout_detail(FakeAdapter(), db, USER, "no_such_workout_1")
