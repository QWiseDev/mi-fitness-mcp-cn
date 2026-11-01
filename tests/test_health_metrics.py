"""扩展指标序列与周期健康报告的单元测试。"""

from datetime import datetime

import pytest

from mi_fitness_mcp.models import (
    BodyMeasurement,
    DailyActivity,
    HeartRateSample,
    SleepSession,
    SpO2Sample,
    StressSample,
)
from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.storage import Database

USER = "u1"


def make_service(tmp_path):
    db = Database(tmp_path / "test.db")
    return QueryService(db, USER), db


def insert_activity(db, date, steps):
    db.insert_daily_activity(
        DailyActivity(
            id=f"a-{date}",
            provider="mi_fitness",
            source_type="cloud_session",
            user_id=USER,
            date=date,
            steps=steps,
            distance_m=steps * 0.7,
            active_kcal=steps / 100,
        )
    )


def test_activity_series_unchanged(tmp_path):
    service, db = make_service(tmp_path)
    insert_activity(db, "2026-10-16", 5000)
    insert_activity(db, "2026-10-17", 7000)

    series = service.get_metric_series("steps", "2026-10-01", "2026-10-31")

    assert series == [{"date": "2026-10-16", "value": 5000}, {"date": "2026-10-17", "value": 7000}]


def test_weight_series_takes_last_measurement_of_day(tmp_path):
    service, db = make_service(tmp_path)
    for record_id, day, hour, weight in (
        ("w1", "2026-10-16", 7, 100.0),
        ("w2", "2026-10-16", 22, 101.5),
        ("w3", "2026-10-17", 8, 101.2),
    ):
        db.insert_body_measurement(
            BodyMeasurement(
                id=record_id,
                provider="mi_fitness",
                source_type="cloud_session",
                user_id=USER,
                timestamp=datetime.fromisoformat(f"{day}T{hour:02d}:00:00"),
                weight_kg=weight,
            )
        )

    series = service.get_metric_series("weight_kg", "2026-10-01", "2026-10-31")

    assert series == [
        {"date": "2026-10-16", "value": 101.5},
        {"date": "2026-10-17", "value": 101.2},
    ]


def test_sleep_minutes_sums_sessions_and_week_avg(tmp_path):
    service, db = make_service(tmp_path)
    for record_id, start, end, minutes in (
        ("s1", "2026-10-16T23:10:00", "2026-10-17T07:30:00", 500),
        ("s2", "2026-10-18T01:00:00", "2026-10-18T07:40:00", 400),
    ):
        db.insert_sleep_session(
            SleepSession(
                id=record_id,
                provider="mi_fitness",
                source_type="cloud_session",
                user_id=USER,
                sleep_id=record_id,
                start_at=datetime.fromisoformat(start),
                end_at=datetime.fromisoformat(end),
                duration_minutes=minutes,
                time_asleep_minutes=minutes - 30,
                time_awake_minutes=30,
            )
        )

    daily = service.get_metric_series("sleep_minutes", "2026-10-01", "2026-10-31")
    assert daily == [{"date": "2026-10-16", "value": 500}, {"date": "2026-10-18", "value": 400}]

    weekly = service.get_metric_series(
        "sleep_minutes", "2026-10-01", "2026-10-31", granularity="week", aggregation="avg"
    )
    # 10-16（周五）与 10-18（周日）同属 10-12 开始的那一周
    assert weekly == [{"date": "2026-10-12", "value": 450}]


def test_resting_heart_rate_averages_and_excludes_passive(tmp_path):
    service, db = make_service(tmp_path)
    for record_id, day, hour, bpm, sample_type in (
        ("h1", "2026-10-16", 8, 60, "resting"),
        ("h2", "2026-10-16", 21, 64, "resting"),
        ("h3", "2026-10-16", 12, 90, "passive"),
        ("h4", "2026-10-17", 8, 58, "resting"),
    ):
        db.insert_heart_rate_sample(
            HeartRateSample(
                id=record_id,
                provider="mi_fitness",
                source_type="cloud_session",
                user_id=USER,
                timestamp=datetime.fromisoformat(f"{day}T{hour:02d}:00:00"),
                bpm=bpm,
                sample_type=sample_type,
            )
        )

    series = service.get_metric_series("resting_heart_rate", "2026-10-01", "2026-10-31")

    assert series == [{"date": "2026-10-16", "value": 62.0}, {"date": "2026-10-17", "value": 58.0}]


def test_spo2_and_stress_daily_averages(tmp_path):
    service, db = make_service(tmp_path)
    for record_id, hour, pct in (("p1", 9, 97), ("p2", 21, 99)):
        db.insert_spo2_sample(
            SpO2Sample(
                id=record_id,
                provider="mi_fitness",
                source_type="cloud_session",
                user_id=USER,
                timestamp=datetime(2026, 10, 16, hour),
                spo2_pct=pct,
            )
        )
    for record_id, hour, score in (("t1", 9, 30), ("t2", 21, 50)):
        db.insert_stress_sample(
            StressSample(
                id=record_id,
                provider="mi_fitness",
                source_type="cloud_session",
                user_id=USER,
                timestamp=datetime(2026, 10, 16, hour),
                stress_score=score,
                level="medium",
            )
        )

    assert service.get_metric_series("spo2_pct", "2026-10-01", "2026-10-31") == [
        {"date": "2026-10-16", "value": 98.0}
    ]
    assert service.get_metric_series("stress_score", "2026-10-01", "2026-10-31") == [
        {"date": "2026-10-16", "value": 40.0}
    ]


def test_unknown_metric_raises(tmp_path):
    service, _ = make_service(tmp_path)
    with pytest.raises(ValueError, match="weight"):
        service.get_metric_series("body_fat", "2026-10-01", "2026-10-31")


def test_health_report_totals_and_averages(tmp_path):
    service, db = make_service(tmp_path)
    insert_activity(db, "2026-10-16", 5000)
    insert_activity(db, "2026-10-17", 7000)
    db.insert_sleep_session(
        SleepSession(
            id="s1",
            provider="mi_fitness",
            source_type="cloud_session",
            user_id=USER,
            sleep_id="s1",
            start_at=datetime(2026, 10, 16, 23, 10),
            end_at=datetime(2026, 10, 17, 7, 10),
            duration_minutes=480,
            time_asleep_minutes=440,
            time_awake_minutes=40,
        )
    )
    db.insert_heart_rate_sample(
        HeartRateSample(
            id="h1",
            provider="mi_fitness",
            source_type="cloud_session",
            user_id=USER,
            timestamp=datetime(2026, 10, 16, 8),
            bpm=60,
            sample_type="resting",
        )
    )
    db.insert_spo2_sample(
        SpO2Sample(
            id="p1",
            provider="mi_fitness",
            source_type="cloud_session",
            user_id=USER,
            timestamp=datetime(2026, 10, 16, 9),
            spo2_pct=98,
        )
    )
    db.insert_stress_sample(
        StressSample(
            id="t1",
            provider="mi_fitness",
            source_type="cloud_session",
            user_id=USER,
            timestamp=datetime(2026, 10, 16, 9),
            stress_score=40,
            level="medium",
        )
    )

    report = service.get_health_report("2026-10-16", "2026-10-17")

    assert report["days_with_data"] == 2
    assert report["totals"]["steps"] == 12000
    assert report["totals"]["sleep_minutes"] == 480
    assert report["averages"]["steps"] == 6000.0
    # 均值只统计有数据的天：17 日无睡眠，不参与平均
    assert report["averages"]["sleep_minutes"] == 480.0
    assert report["averages"]["resting_heart_rate"] == 60.0
    assert report["averages"]["spo2_pct"] == 98.0
    assert report["averages"]["stress_score"] == 40.0
    day16 = report["days"][0]
    assert (
        day16["steps"] == 5000
        and day16["sleep_minutes"] == 480
        and day16["resting_heart_rate"] == 60.0
    )
    day17 = report["days"][1]
    assert day17["steps"] == 7000 and day17["sleep_minutes"] is None and day17["spo2_pct"] is None
