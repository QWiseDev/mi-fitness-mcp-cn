"""运动游标增量同步与全类型数据新鲜度的单元测试。"""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
from mi_fitness_mcp.models import DailyActivity, HeartRateSample
from mi_fitness_mcp.services.latest_data import get_latest_data
from mi_fitness_mcp.services.sync_service import sync_sport_records_incremental
from mi_fitness_mcp.storage import Database

USER = "u1"
TZ = timezone(timedelta(hours=8))


def make_record(time=1793427743, duration=3600):
    value = json.dumps(
        {"start_time": time, "end_time": time + duration, "duration": duration, "calories": 300}
    )
    return {
        "sid": "s1",
        "key": "indoor_walking",
        "time": time,
        "category": "walking",
        "zone_offset": 28800,
        "zone_name": "Asia/Shanghai",
        "value": value,
    }


async def test_fetch_sport_records_by_watermark_paginates(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id=USER, pass_token="p1")
    calls = []

    async def fake_request(base_url, api_path, payload):
        calls.append(payload["watermark"])
        if payload["watermark"] == 0:
            return {"sport_records": [make_record()], "watermark": 100, "has_more": True}
        return {
            "sport_records": [make_record(time=1793430000)],
            "watermark": 200,
            "has_more": False,
        }

    monkeypatch.setattr(adapter, "_request", fake_request)
    result = await adapter.fetch_sport_records_by_watermark(0)

    assert calls == [0, 100]
    assert len(result["sport_records"]) == 2
    assert result["watermark"] == 200
    assert result["has_more"] is False


async def test_fetch_sport_records_by_watermark_stops_on_stuck_cursor(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id=USER, pass_token="p1")

    async def fake_request(base_url, api_path, payload):
        return {
            "sport_records": [make_record()],
            "watermark": payload["watermark"],
            "has_more": True,
        }

    monkeypatch.setattr(adapter, "_request", fake_request)
    result = await adapter.fetch_sport_records_by_watermark(50)

    # 游标不前进时立即终止，不进入安全上限的空转
    assert len(result["sport_records"]) == 1
    assert result["watermark"] == 50
    assert result["has_more"] is False


async def test_sync_sport_records_incremental_upserts_and_returns_cursor(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    adapter = MiFitnessCloudAdapter(user_id=USER, pass_token="p1")
    seen_watermarks = []

    async def fake_fetch(watermark, region=None):
        seen_watermarks.append(watermark)
        records = [make_record()] if watermark == 50 else []
        return {"sport_records": records, "watermark": 300, "has_more": False}

    monkeypatch.setattr(adapter, "fetch_sport_records_by_watermark", fake_fetch)

    result = await sync_sport_records_incremental(adapter, db, 50)
    assert seen_watermarks == [50]
    assert result["records_fetched"] == 1
    assert result["records_processed"] == 1
    assert result["watermark"] == 300

    rows = db.query_workouts(USER, "2026-01-01", "2026-12-31")
    assert len(rows) == 1

    # 幂等：同一游标/新游标无变更时不再产生数据
    result = await sync_sport_records_incremental(adapter, db, 300)
    assert result["records_fetched"] == 0
    assert result["records_processed"] == 0
    assert len(db.query_workouts(USER, "2026-01-01", "2026-12-31")) == 1


async def test_get_latest_data_includes_freshness(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_daily_activity(
        DailyActivity(
            id="a",
            provider="mi_fitness",
            source_type="cloud_session",
            user_id=USER,
            date="2026-11-21",
            steps=100,
            distance_m=1,
            active_kcal=1,
        )
    )
    db.insert_heart_rate_sample(
        HeartRateSample(
            id="h",
            provider="mi_fitness",
            source_type="cloud_session",
            user_id=USER,
            timestamp=datetime.now(UTC) - timedelta(hours=2),
            bpm=60,
            sample_type="resting",
        )
    )

    class FakeAdapter:
        def is_connected(self):
            return True

        async def get_max_watermark(self):
            return 42

        async def get_latest_sport_record(self):
            return None

    result = await get_latest_data(FakeAdapter(), db, USER)

    assert result["cloud_watermark"] == 42
    assert result["latest_workout"] is None
    freshness = result["freshness"]
    assert freshness["daily_activity"]["latest_date"] == "2026-11-21"
    assert freshness["heart_rate"]["age_hours"] == pytest.approx(2.0, abs=0.1)
    assert freshness["sleep"]["latest"] is None
