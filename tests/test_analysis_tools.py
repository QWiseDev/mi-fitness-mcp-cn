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


def test_sleep_analysis_nights_and_summary(tmp_path):
    db = Database(tmp_path / "test.db")
    service = QueryService(db, USER)
    insert_sleep(
        db,
        "n1",
        datetime(2026, 11, 9, 23, 10, tzinfo=TZ),
        datetime(2026, 11, 10, 7, 10, tzinfo=TZ),
        480,
        440,
        {"deep": 60, "light": 240, "rem": 120, "awake": 60},
        score=85,
        efficiency=90,
    )
    insert_sleep(
        db,
        "n2",
        datetime(2026, 11, 10, 23, 20, tzinfo=TZ),
        datetime(2026, 11, 11, 7, 20, tzinfo=TZ),
        480,
        430,
        {"deep": 50, "light": 250, "rem": 110, "awake": 70},
        score=82,
    )
    insert_sleep(
        db,
        "n3",
        datetime(2026, 11, 14, 23, 50, tzinfo=TZ),
        datetime(2026, 11, 15, 6, 50, tzinfo=TZ),
        420,
        390,
        {"deep": 40, "light": 240, "rem": 90, "awake": 50},
        score=78,
    )
    insert_sleep(
        db,
        "n4",
        datetime(2026, 11, 13, 23, 30, tzinfo=TZ),
        datetime(2026, 11, 14, 6, 40, tzinfo=TZ),
        420,
        380,
        {"deep": 45, "light": 235, "rem": 85, "awake": 55},
        score=76,
    )
    insert_sleep(
        db,
        "nap1",
        datetime(2026, 11, 10, 14, 0, tzinfo=TZ),
        datetime(2026, 11, 10, 14, 30, tzinfo=TZ),
        30,
        25,
        {"light": 30},
        is_nap=True,
    )

    result = service.get_sleep_analysis("2026-11-09", "2026-11-15")

    assert result["nights_count"] == 4
    assert result["naps_count"] == 1
    assert result["naps_total_minutes"] == 30
    night1 = result["nights"][0]
    assert night1["date"] == "2026-11-10"  # 起床日归属
    assert night1["deep_minutes"] == 60
    assert night1["efficiency_pct"] == 92.3  # 480 入睡 / (480+40) 卧床
    assert night1["sleep_efficiency"] == 90  # 云端官方值
    assert night1["avg_hr"] == 65
    summary = result["summary"]
    assert summary["avg_duration_minutes"] == 450.0
    # 效率优先取官方值：n1=90（官方），其余夜回退到计算值
    assert summary["avg_efficiency_pct"] == round((90 + 90.6 + 93.3 + 91.3) / 4, 1)
    assert summary["weekday_avg_minutes"] == 480.0
    assert summary["weekend_avg_minutes"] == 420.0
    assert summary["avg_bedtime"] == "23:28"  # 23:10/23:20/23:50/23:30 跨午夜折算后的均值
    assert summary["avg_wake_time"] == "07:00"
    assert summary["stage_share_pct"]["deep"] == round(195 / 1800 * 100, 1)
    assert summary["trend"] == {"first_half_avg_minutes": 480.0, "second_half_avg_minutes": 420.0}


def test_compare_periods_deltas_only_on_averages(tmp_path):
    db = Database(tmp_path / "test.db")
    service = QueryService(db, USER)
    for day, steps in (
        ("2026-11-02", 5000),
        ("2026-11-03", 5000),
        ("2026-11-09", 7000),
        ("2026-11-10", 7000),
    ):
        insert_activity(db, day, steps)
    for day, bpm in (
        ("2026-11-02", 60),
        ("2026-11-03", 60),
        ("2026-11-09", 65),
        ("2026-11-10", 65),
    ):
        db.insert_heart_rate_sample(
            HeartRateSample(
                id=f"hr-{day}",
                provider="mi_fitness",
                source_type="cloud_session",
                user_id=USER,
                timestamp=datetime.fromisoformat(f"{day}T08:00:00+08:00"),
                bpm=bpm,
                sample_type="resting",
            )
        )

    result = service.compare_periods("2026-11-02", "2026-11-03", "2026-11-09", "2026-11-10")

    assert result["period_1"]["totals"]["steps"] == 10000
    assert result["period_2"]["totals"]["steps"] == 14000
    assert result["deltas"]["steps"] == -2000.0
    assert result["deltas"]["resting_heart_rate"] == -5.0
    assert "totals" not in result["deltas"]


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
