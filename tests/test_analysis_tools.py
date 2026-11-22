"""睡眠分析 / 周期对比 / 异常检测的单元测试。"""

from datetime import date, datetime, timedelta, timezone

from mi_fitness_mcp.models import (
    DailyActivity,
    HeartRateSample,
    SleepSession,
    SleepStage,
    SpO2Sample,
    StressSample,
)
from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.storage import Database

TZ = timezone(timedelta(hours=8))
USER = "u1"


def make_service(tmp_path):
    return QueryService(Database(tmp_path / "test.db"), USER)


def insert_sleep(
    db, sleep_id, start, end, duration, asleep, stages, score=None, is_nap=False, efficiency=None
):
    db.insert_sleep_session(
        SleepSession(
            id=sleep_id,
            provider="mi_fitness",
            source_type="cloud_session",
            user_id=USER,
            sleep_id=sleep_id,
            start_at=start,
            end_at=end,
            duration_minutes=duration,
            time_asleep_minutes=asleep,
            time_awake_minutes=duration - asleep,
            sleep_score=score,
            is_nap=is_nap,
            sleep_efficiency=efficiency,
            avg_hr=65,
            stages=[SleepStage(stage=name, minutes=minutes) for name, minutes in stages.items()],
        )
    )


def insert_activity(db, day, steps):
    db.insert_daily_activity(
        DailyActivity(
            id=f"a-{day}",
            provider="mi_fitness",
            source_type="cloud_session",
            user_id=USER,
            date=day,
            steps=steps,
            distance_m=steps * 0.7,
            active_kcal=steps / 100,
        )
    )


def insert_daily_metric(db, day, rhr=None, spo2=None, stress=None, sleep_minutes=None):
    if rhr is not None:
        db.insert_heart_rate_sample(
            HeartRateSample(
                id=f"hr-{day}",
                provider="mi_fitness",
                source_type="cloud_session",
                user_id=USER,
                timestamp=datetime.fromisoformat(f"{day}T08:00:00+08:00"),
                bpm=rhr,
                sample_type="resting",
            )
        )
    if spo2 is not None:
        db.insert_spo2_sample(
            SpO2Sample(
                id=f"p-{day}",
                provider="mi_fitness",
                source_type="cloud_session",
                user_id=USER,
                timestamp=datetime.fromisoformat(f"{day}T09:00:00+08:00"),
                spo2_pct=spo2,
            )
        )
    if stress is not None:
        db.insert_stress_sample(
            StressSample(
                id=f"t-{day}",
                provider="mi_fitness",
                source_type="cloud_session",
                user_id=USER,
                timestamp=datetime.fromisoformat(f"{day}T09:00:00+08:00"),
                stress_score=stress,
                level="low" if stress < 40 else "medium",
            )
        )
    if sleep_minutes is not None:
        insert_sleep(
            db,
            f"s-{day}",
            datetime.fromisoformat(f"{day}T10:00:00+08:00"),
            datetime.fromisoformat(f"{day}T10:00:00+08:00") + timedelta(minutes=sleep_minutes),
            sleep_minutes,
            sleep_minutes - 30,
            {"deep": 60, "light": 240, "rem": 90, "awake": 30},
        )


def test_detect_anomalies_flags_resting_hr_and_sleep_drop(tmp_path):
    db = Database(tmp_path / "test.db")
    service = QueryService(db, USER)
    for offset in range(13):
        day = (date(2026, 10, 20) + timedelta(days=offset)).isoformat()
        recent = offset >= 10
        insert_daily_metric(
            db,
            day,
            rhr=66 if recent else 60,
            spo2=96 if recent else 97,
            stress=25 if recent else 20,
            sleep_minutes=420 if recent else 480,
        )

    result = service.detect_anomalies("2026-10-20", "2026-11-01", recent_days=3)

    metrics = {f["metric"]: f for f in result["findings"]}
    assert set(metrics) == {"resting_heart_rate", "sleep_minutes"}
    assert metrics["resting_heart_rate"]["delta"] == 6.0
    assert metrics["resting_heart_rate"]["severity"] == "warn"
    assert metrics["sleep_minutes"]["delta"] == -60.0
    assert result["baseline_days"] == 10


def test_detect_anomalies_needs_enough_baseline(tmp_path):
    db = Database(tmp_path / "test.db")
    service = QueryService(db, USER)
    for offset in range(4):
        day = (date(2026, 11, 8) + timedelta(days=offset)).isoformat()
        insert_daily_metric(db, day, rhr=70, spo2=97, stress=20, sleep_minutes=480)

    result = service.detect_anomalies("2026-11-08", "2026-11-11", recent_days=3)

    assert result["findings"] == []
