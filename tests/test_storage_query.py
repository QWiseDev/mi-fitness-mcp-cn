from datetime import datetime

from mi_fitness_mcp.models import BodyMeasurement, DailyActivity, HeartRateSample
from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.storage import Database


def test_storage_and_query_roundtrip(tmp_path):
    db = Database(tmp_path / "test.db")

    activity = DailyActivity(
        id="a1",
        provider="mi_fitness",
        source_type="cloud_session",
        user_id="u1",
        date="2025-04-01",
        steps=1000,
        distance_m=800,
        active_kcal=50,
    )
    hr = HeartRateSample(
        id="hr1",
        provider="mi_fitness",
        source_type="cloud_session",
        user_id="u1",
        timestamp=datetime(2025, 4, 1, 12, 0, 0),
        bpm=70,
        sample_type="passive",
    )
    body = BodyMeasurement(
        id="w1",
        provider="mi_fitness",
        source_type="cloud_session",
        user_id="u1",
        timestamp=datetime(2025, 4, 1, 7, 0, 0),
        weight_kg=101.5,
        bmi=28.0,
    )

    db.upsert("daily_activity", [activity])
    db.upsert("heart_rate", [hr])
    db.upsert("body_measurements", [body])

    query = QueryService(db, "u1")
    assert len(query.get_daily_summaries("2025-04-01", "2025-04-01")) == 1
    assert len(query.get_heart_rate_samples("2025-04-01", "2025-04-01")) == 1
    assert len(query.get_body_measurements("2025-04-01", "2025-04-01")) == 1


def test_sleep_official_columns_migrate_on_existing_db(tmp_path):
    """旧版 sleep_sessions 表打开时应自动补齐官方扩展列。"""
    import sqlite3

    from mi_fitness_mcp.models import SleepSession, SleepStage

    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE sleep_sessions (
            id TEXT PRIMARY KEY, provider TEXT NOT NULL, source_type TEXT NOT NULL,
            source_record_id TEXT, user_id TEXT NOT NULL, device_id TEXT,
            timezone TEXT DEFAULT 'UTC', collected_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sleep_id TEXT NOT NULL, start_at TIMESTAMP NOT NULL, end_at TIMESTAMP NOT NULL,
            duration_minutes INTEGER NOT NULL, time_asleep_minutes INTEGER NOT NULL,
            time_awake_minutes INTEGER NOT NULL, sleep_score INTEGER,
            is_nap BOOLEAN DEFAULT FALSE, stages TEXT, UNIQUE(user_id, sleep_id)
        )
        """
    )
    conn.commit()
    conn.close()

    db = Database(db_path)  # 打开即触发迁移
    db.insert_sleep_session(
        SleepSession(
            id="s1",
            provider="mi_fitness",
            source_type="cloud_session",
            user_id="u1",
            sleep_id="s1",
            start_at=datetime(2026, 11, 9, 23, 10),
            end_at=datetime(2026, 11, 10, 7, 10),
            duration_minutes=480,
            time_asleep_minutes=480,
            time_awake_minutes=55,
            sleep_efficiency=82,
            awake_count=2,
            avg_hr=67,
            avg_spo2=95,
            avg_breath=16,
            avg_hrv=41,
            raw_payload={"sleep_efficiency": 82, "hrv_median": 41},
            stages=[SleepStage(stage="light", minutes=480)],
        )
    )

    query = QueryService(db, "u1")
    sessions = query.get_sleep_sessions("2026-11-09", "2026-11-10")
    assert len(sessions) == 1
    session = sessions[0]
    assert session["sleep_efficiency"] == 82
    assert session["avg_hr"] == 67 and session["avg_hrv"] == 41
    assert session["raw_payload"]["hrv_median"] == 41
