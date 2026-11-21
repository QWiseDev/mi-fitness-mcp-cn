"""Query service for retrieving data from database."""

from contextlib import suppress
from datetime import date, datetime, timedelta
from typing import Any

from mi_fitness_mcp.storage import Database


class QueryService:
    """Service for querying fitness data from local database."""

    def __init__(self, db: Database, user_id: str):
        """Initialize query service.

        Args:
            db: Database instance
            user_id: User identifier
        """
        self.db = db
        self.user_id = user_id

    def get_daily_summaries(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Get daily activity summaries for date range."""
        records = self.db.query_daily_activity(self.user_id, start_date, end_date)

        # 按日期分组并聚合
        summaries = {}
        for record in records:
            date = record["date"]
            if date not in summaries:
                summaries[date] = {
                    "date": date,
                    "steps": 0,
                    "distance_m": 0,
                    "active_kcal": 0,
                    "total_kcal": 0,
                    "floors": 0,
                    "active_minutes": 0,
                }

            summaries[date]["steps"] += record.get("steps", 0)
            summaries[date]["distance_m"] += record.get("distance_m", 0)
            summaries[date]["active_kcal"] += record.get("active_kcal", 0)
            if record.get("total_kcal"):
                summaries[date]["total_kcal"] += record["total_kcal"]
            if record.get("floors"):
                summaries[date]["floors"] += record["floors"]
            if record.get("active_minutes"):
                summaries[date]["active_minutes"] += record["active_minutes"]

        return list(summaries.values())

    def get_metric_series(
        self,
        metric: str,
        start_date: str,
        end_date: str,
        granularity: str = "day",
        aggregation: str = "sum",
    ) -> list[dict[str, Any]]:
        """Get time series for a metric (daily rows, optional week/month aggregation)."""
        daily = self._metric_daily_values(metric, start_date, end_date)
        series = [{"date": day, "value": value} for day, value in sorted(daily.items())]

        # 按需执行周/月聚合
        if granularity == "week":
            series = self._aggregate_by_week(series, aggregation)
        elif granularity == "month":
            series = self._aggregate_by_month(series, aggregation)

        return series

    def _metric_daily_values(self, metric: str, start_date: str, end_date: str) -> dict[str, Any]:
        """Compute per-day values for a metric; returns {date: value} covering days with data.

        活动类指标来自每日活动汇总；健康类指标按天从各明细表聚合：
        - weight_kg：同日多次测量取当日最后一次
        - sleep_minutes：当日开始（按会话 start_at 归属日期）的睡眠会话时长求和，含小睡
        - resting_heart_rate / spo2_pct / stress_score：当日样本均值
        """
        if metric in (
            "steps",
            "distance_m",
            "active_kcal",
            "total_kcal",
            "floors",
            "active_minutes",
        ):
            return {
                summary["date"]: summary[metric]
                for summary in self.get_daily_summaries(start_date, end_date)
                if summary.get(metric) is not None
            }

        daily: dict[str, Any] = {}

        if metric == "weight_kg":
            # 查询结果按时间升序，覆盖写入即得当日最后一次测量
            for row in self.db.query_body_measurements(self.user_id, start_date, end_date):
                if row.get("weight_kg") is not None:
                    daily[str(row["timestamp"])[:10]] = row["weight_kg"]
            return daily

        if metric == "sleep_minutes":
            for row in self.db.query_sleep_sessions(self.user_id, start_date, end_date):
                date_key = str(row["start_at"])[:10]
                daily[date_key] = daily.get(date_key, 0) + (row.get("duration_minutes") or 0)
            return daily

        if metric in ("resting_heart_rate", "spo2_pct", "stress_score"):
            if metric == "resting_heart_rate":
                rows = self.db.query_heart_rate_samples(self.user_id, start_date, end_date)
                rows = [row for row in rows if row.get("sample_type") == "resting"]
                value_key = "bpm"
            elif metric == "spo2_pct":
                rows = self.db.query_spo2_samples(self.user_id, start_date, end_date)
                value_key = "spo2_pct"
            else:
                rows = self.db.query_stress_samples(self.user_id, start_date, end_date)
                value_key = "stress_score"

            buckets: dict[str, list[float]] = {}
            for row in rows:
                value = row.get(value_key)
                if value is not None:
                    buckets.setdefault(str(row["timestamp"])[:10], []).append(value)
            return {
                date_key: round(sum(values) / len(values), 1)
                for date_key, values in sorted(buckets.items())
            }

        raise ValueError(
            f"未知指标 {metric!r}，可选：steps, distance_m, active_kcal, total_kcal, "
            "floors, active_minutes, weight_kg, sleep_minutes, resting_heart_rate, spo2_pct, stress_score"
        )

    def get_health_report(self, start_date: str, end_date: str) -> dict[str, Any]:
        """Aggregate activity, sleep, resting HR, SpO2 and stress for a range into one report."""
        activity_by_date = {
            summary["date"]: summary for summary in self.get_daily_summaries(start_date, end_date)
        }
        sleep_daily = self._metric_daily_values("sleep_minutes", start_date, end_date)
        rhr_daily = self._metric_daily_values("resting_heart_rate", start_date, end_date)
        spo2_daily = self._metric_daily_values("spo2_pct", start_date, end_date)
        stress_daily = self._metric_daily_values("stress_score", start_date, end_date)

        all_days = sorted(
            set(activity_by_date)
            | set(sleep_daily)
            | set(rhr_daily)
            | set(spo2_daily)
            | set(stress_daily)
        )
        days = []
        for day in all_days:
            activity = activity_by_date.get(day, {})
            days.append(
                {
                    "date": day,
                    "steps": activity.get("steps"),
                    "distance_m": activity.get("distance_m"),
                    "active_kcal": activity.get("active_kcal"),
                    "active_minutes": activity.get("active_minutes"),
                    "sleep_minutes": sleep_daily.get(day),
                    "resting_heart_rate": rhr_daily.get(day),
                    "spo2_pct": spo2_daily.get(day),
                    "stress_score": stress_daily.get(day),
                }
            )

        def _total(key: str) -> float:
            return sum(day[key] or 0 for day in days)

        def _avg(key: str) -> float | None:
            values = [day[key] for day in days if day[key] is not None]
            return round(sum(values) / len(values), 1) if values else None

        return {
            "start_date": start_date,
            "end_date": end_date,
            "days_with_data": len(days),
            "totals": {
                "steps": _total("steps"),
                "distance_m": _total("distance_m"),
                "active_kcal": _total("active_kcal"),
                "active_minutes": _total("active_minutes"),
                "sleep_minutes": _total("sleep_minutes"),
            },
            "averages": {
                "steps": _avg("steps"),
                "sleep_minutes": _avg("sleep_minutes"),
                "resting_heart_rate": _avg("resting_heart_rate"),
                "spo2_pct": _avg("spo2_pct"),
                "stress_score": _avg("stress_score"),
            },
            "days": days,
        }

    def get_sleep_analysis(self, start_date: str, end_date: str) -> dict[str, Any]:
        """Aggregate main-sleep sessions for a range: per-night rows + summary stats.

        会话按 start_at 归属日期（与 sleep_minutes 序列一致）；小睡只计总量，
        不进逐晚明细。
        """
        sessions = self.get_sleep_sessions(start_date, end_date, include_naps=True)
        main = [s for s in sessions if not s.get("is_nap")]
        naps = [s for s in sessions if s.get("is_nap")]

        nights = []
        for session in sorted(main, key=lambda s: s["start_at"]):
            # 同一分期会有多段（每晚十几段很常见），必须累加而不是覆盖
            stages: dict[str, int] = {}
            for stage in session.get("stages") or []:
                stages[stage["stage"]] = stages.get(stage["stage"], 0) + (stage.get("minutes") or 0)
            duration = session.get("duration_minutes") or 0  # 实际入睡分钟
            awake = session.get("time_awake_minutes") or 0
            bed_total = duration + awake
            nights.append(
                {
                    "date": str(session["start_at"])[:10],
                    "bedtime": str(session["start_at"])[11:16],
                    "wake_time": str(session["end_at"])[11:16],
                    "duration_minutes": session["duration_minutes"],
                    "time_asleep_minutes": session["time_asleep_minutes"],
                    "efficiency_pct": round(duration / bed_total * 100, 1) if bed_total else None,
                    "sleep_score": session.get("sleep_score"),
                    "sleep_efficiency": session.get("sleep_efficiency"),
                    "awake_count": session.get("awake_count"),
                    "avg_hr": session.get("avg_hr"),
                    "avg_spo2": session.get("avg_spo2"),
                    "avg_breath": session.get("avg_breath"),
                    "avg_hrv": session.get("avg_hrv"),
                    "deep_minutes": stages.get("deep"),
                    "light_minutes": stages.get("light"),
                    "rem_minutes": stages.get("rem"),
                    "awake_minutes": stages.get("awake"),
                }
            )

        def _avg(values: list) -> float | None:
            return round(sum(values) / len(values), 1) if values else None

        durations = [n["duration_minutes"] for n in nights if n["duration_minutes"] is not None]
        asleep_values = [
            n["time_asleep_minutes"] for n in nights if n["time_asleep_minutes"] is not None
        ]
        # 效率优先取云端官方值，缺失时回退到 入睡/(入睡+清醒)
        efficiency_values = [
            n["sleep_efficiency"] if n["sleep_efficiency"] is not None else n["efficiency_pct"]
            for n in nights
        ]
        efficiency_values = [v for v in efficiency_values if v is not None]
        scores = [n["sleep_score"] for n in nights if n["sleep_score"] is not None]

        stage_sums = {}
        for stage in ("deep", "light", "rem", "awake"):
            values = [n[f"{stage}_minutes"] or 0 for n in nights]
            stage_sums[stage] = sum(values)
        stage_total = sum(stage_sums.values())

        bedtime_minutes = []
        for night in nights:
            minutes = self._clock_minutes(night["bedtime"])
            if minutes is not None:
                # 跨午夜的就寝时间（00:xx-11:xx）折算到前一天晚上，避免均值绕回
                bedtime_minutes.append(minutes + 1440 if minutes < 720 else minutes)
        wake_minutes = [self._clock_minutes(n["wake_time"]) for n in nights]
        wake_minutes = [m for m in wake_minutes if m is not None]

        weekday = [
            n["duration_minutes"]
            for n in nights
            if n["duration_minutes"] is not None and date.fromisoformat(n["date"]).weekday() < 5
        ]
        weekend = [
            n["duration_minutes"]
            for n in nights
            if n["duration_minutes"] is not None and date.fromisoformat(n["date"]).weekday() >= 5
        ]
        half = len(durations) // 2

        return {
            "start_date": start_date,
            "end_date": end_date,
            "nights_count": len(nights),
            "nights": nights,
            "summary": {
                "avg_duration_minutes": _avg(durations),
                "avg_time_asleep_minutes": _avg(asleep_values),
                "avg_efficiency_pct": _avg(efficiency_values),
                "avg_sleep_score": _avg(scores),
                "avg_bedtime": self._fmt_clock(_avg(bedtime_minutes) % 1440)
                if bedtime_minutes
                else None,
                "avg_wake_time": self._fmt_clock(_avg(wake_minutes)) if wake_minutes else None,
                "stage_share_pct": (
                    {
                        stage: round(sums / stage_total * 100, 1)
                        for stage, sums in stage_sums.items()
                    }
                    if stage_total
                    else None
                ),
                "weekday_avg_minutes": _avg(weekday),
                "weekend_avg_minutes": _avg(weekend),
                "trend": (
                    {
                        "first_half_avg_minutes": _avg(durations[:half]),
                        "second_half_avg_minutes": _avg(durations[half:]),
                    }
                    if len(durations) >= 4
                    else None
                ),
            },
            "naps_count": len(naps),
            "naps_total_minutes": sum(s.get("duration_minutes") or 0 for s in naps),
        }

    def compare_periods(
        self,
        start_1: str,
        end_1: str,
        start_2: str,
        end_2: str,
    ) -> dict[str, Any]:
        """Compare two date ranges (period_1 vs period_2) via health reports.

        合计对区间长度敏感，只对平均值计算差值；合计原样给出。
        """
        report_1 = self.get_health_report(start_1, end_1)
        report_2 = self.get_health_report(start_2, end_2)
        deltas = {
            metric: (
                round((report_1["averages"][metric] or 0) - (report_2["averages"][metric] or 0), 1)
                if report_1["averages"][metric] is not None
                and report_2["averages"][metric] is not None
                else None
            )
            for metric in report_1["averages"]
        }
        return {
            "period_1": {
                "start_date": start_1,
                "end_date": end_1,
                **{k: report_1[k] for k in ("days_with_data", "totals", "averages")},
            },
            "period_2": {
                "start_date": start_2,
                "end_date": end_2,
                **{k: report_2[k] for k in ("days_with_data", "totals", "averages")},
            },
            "deltas": deltas,
        }

    def detect_anomalies(
        self, start_date: str, end_date: str, recent_days: int = 7
    ) -> dict[str, Any]:
        """Compare the last `recent_days` of a window against the baseline before it.

        规则（基线与近期都至少有数据才判）：
        - resting_heart_rate：近期均值比基线高 >=5 bpm → warn
        - spo2_pct：近期均值比基线低 >=2 pct → warn
        - stress_score：近期均值比基线高 >=10 → info
        - sleep_minutes：近期均值比基线低 >=45 分钟或 15% → warn
        """
        all_daily = {
            metric: self._metric_daily_values(metric, start_date, end_date)
            for metric in ("resting_heart_rate", "spo2_pct", "stress_score", "sleep_minutes")
        }
        dates = sorted(set().union(*(values.keys() for values in all_daily.values())))
        if not dates:
            return {
                "start_date": start_date,
                "end_date": end_date,
                "recent_days": recent_days,
                "findings": [],
                "note": "窗口内无数据",
            }
        recent_dates = set(dates[-recent_days:])

        findings = []
        baseline_days = 0
        rules = {
            "resting_heart_rate": ("higher", 5.0, "warn"),
            "spo2_pct": ("lower", 2.0, "warn"),
            "stress_score": ("higher", 10.0, "info"),
            "sleep_minutes": ("lower", 45.0, "warn"),
        }
        for metric, (direction, threshold, severity) in rules.items():
            values = all_daily[metric]
            baseline = [values[d] for d in dates if d not in recent_dates and d in values]
            current = [values[d] for d in dates if d in recent_dates and d in values]
            if metric == "resting_heart_rate":
                baseline_days = len(baseline)
            if len(baseline) < 5 or len(current) < 3:
                continue
            base_avg = sum(baseline) / len(baseline)
            recent_avg = sum(current) / len(current)
            delta = round(recent_avg - base_avg, 1)
            hit = (
                delta >= threshold
                if direction == "higher"
                else base_avg - recent_avg >= threshold
                or (base_avg and recent_avg / base_avg <= 0.85 and metric == "sleep_minutes")
            )
            if hit:
                findings.append(
                    {
                        "metric": metric,
                        "baseline_avg": round(base_avg, 1),
                        "recent_avg": round(recent_avg, 1),
                        "delta": delta,
                        "direction": direction,
                        "severity": severity,
                        "baseline_days": len(baseline),
                        "recent_days_with_data": len(current),
                    }
                )

        return {
            "start_date": start_date,
            "end_date": end_date,
            "recent_days": recent_days,
            "baseline_days": baseline_days,
            "findings": findings,
            "checked": list(rules),
        }

    @staticmethod
    def _clock_minutes(text: str) -> int | None:
        try:
            hour, minute = text.split(":")
            return int(hour) * 60 + int(minute)
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _fmt_clock(minutes: float | int | None) -> str | None:
        if minutes is None:
            return None
        minutes = int(round(minutes)) % 1440
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    def _aggregate_by_week(
        self,
        series: list[dict],
        aggregation: str,
    ) -> list[dict]:
        """Aggregate daily series by week."""
        weeks = {}

        for item in series:
            date = datetime.strptime(item["date"], "%Y-%m-%d")
            # 计算周起始日（周一）
            week_start = date - timedelta(days=date.weekday())
            week_key = week_start.strftime("%Y-%m-%d")

            if week_key not in weeks:
                weeks[week_key] = []
            weeks[week_key].append(item["value"])

        result = []
        for week_key, values in sorted(weeks.items()):
            if aggregation == "sum":
                value = sum(values)
            elif aggregation == "avg":
                value = sum(values) / len(values)
            elif aggregation == "min":
                value = min(values)
            elif aggregation == "max":
                value = max(values)
            else:
                value = sum(values)

            result.append({"date": week_key, "value": value})

        return result

    def _aggregate_by_month(
        self,
        series: list[dict],
        aggregation: str,
    ) -> list[dict]:
        """Aggregate daily series by month."""
        months = {}

        for item in series:
            date = datetime.strptime(item["date"], "%Y-%m-%d")
            month_key = date.strftime("%Y-%m")

            if month_key not in months:
                months[month_key] = []
            months[month_key].append(item["value"])

        result = []
        for month_key, values in sorted(months.items()):
            if aggregation == "sum":
                value = sum(values)
            elif aggregation == "avg":
                value = sum(values) / len(values)
            elif aggregation == "min":
                value = min(values)
            elif aggregation == "max":
                value = max(values)
            else:
                value = sum(values)

            result.append({"date": month_key + "-01", "value": value})

        return result

    def get_sleep_sessions(
        self,
        start_date: str,
        end_date: str,
        include_naps: bool = True,
    ) -> list[dict[str, Any]]:
        """Get sleep sessions for date range."""
        records = self.db.query_sleep_sessions(self.user_id, start_date, end_date)

        sessions = []
        for record in records:
            # 不包含小睡时跳过 nap 记录
            if not include_naps and record.get("is_nap"):
                continue

            session = {
                "sleep_id": record["sleep_id"],
                "start_at": record["start_at"],
                "end_at": record["end_at"],
                "duration_minutes": record["duration_minutes"],
                "time_asleep_minutes": record["time_asleep_minutes"],
                "time_awake_minutes": record["time_awake_minutes"],
                "sleep_score": record.get("sleep_score"),
                "is_nap": record.get("is_nap", False),
                "sleep_efficiency": record.get("sleep_efficiency"),
                "awake_count": record.get("awake_count"),
                "avg_hr": record.get("avg_hr"),
                "max_hr": record.get("max_hr"),
                "min_hr": record.get("min_hr"),
                "avg_spo2": record.get("avg_spo2"),
                "max_spo2": record.get("max_spo2"),
                "min_spo2": record.get("min_spo2"),
                "avg_breath": record.get("avg_breath"),
                "avg_hrv": record.get("avg_hrv"),
                "max_hrv": record.get("max_hrv"),
                "min_hrv": record.get("min_hrv"),
            }

            # 如有睡眠阶段信息则解析
            if record.get("stages"):
                import json

                with suppress(json.JSONDecodeError):
                    session["stages"] = json.loads(record["stages"])

            # 云端完整 payload（HRV 分位、算法版本等全部官方字段）
            if record.get("raw_payload"):
                import json

                with suppress(json.JSONDecodeError):
                    session["raw_payload"] = json.loads(record["raw_payload"])

            sessions.append(session)

        return sessions

    def get_workouts(
        self,
        start_date: str,
        end_date: str,
        activity_types: list[str] | None = None,
        min_duration: int | None = None,
        min_distance_km: float | None = None,
    ) -> list[dict[str, Any]]:
        """Get workouts for date range with optional filters."""
        records = self.db.query_workouts(self.user_id, start_date, end_date)

        workouts = []
        for record in records:
            # 应用过滤条件
            if activity_types and record["activity_type"].lower() not in [
                t.lower() for t in activity_types
            ]:
                continue

            if min_duration and record.get("duration_minutes", 0) < min_duration:
                continue

            if min_distance_km:
                distance_km = (record.get("distance_m") or 0) / 1000
                if distance_km < min_distance_km:
                    continue

            workouts.append(
                {
                    "workout_id": record["workout_id"],
                    "activity_type": record["activity_type"],
                    "start_at": record["start_at"],
                    "end_at": record["end_at"],
                    "duration_minutes": record["duration_minutes"],
                    "distance_m": record.get("distance_m"),
                    "calories_kcal": record.get("calories_kcal"),
                    "avg_heart_rate_bpm": record.get("avg_heart_rate_bpm"),
                    "max_heart_rate_bpm": record.get("max_heart_rate_bpm"),
                    "avg_pace_sec_per_km": record.get("avg_pace_sec_per_km"),
                    "max_pace_sec_per_km": record.get("max_pace_sec_per_km"),
                    "total_steps": record.get("total_steps"),
                }
            )

        return workouts

    def get_body_measurements(
        self,
        start_date: str,
        end_date: str,
        metrics: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get body measurements for date range."""
        records = self.db.query_body_measurements(self.user_id, start_date, end_date)

        measurements = []
        for record in records:
            measurement = {
                "timestamp": record["timestamp"],
                "weight_kg": record["weight_kg"],
            }

            # 添加可选指标
            optional_fields = [
                "bmi",
                "body_fat_pct",
                "muscle_mass_kg",
                "water_pct",
                "bone_mass_kg",
                "visceral_fat_score",
                "basal_metabolism_kcal",
                "metabolic_age",
            ]

            for field in optional_fields:
                if record.get(field) is not None:
                    measurement[field] = record[field]

            # 如指定指标列表则过滤字段
            if metrics:
                filtered = {"timestamp": measurement["timestamp"]}
                for metric in metrics:
                    if metric in measurement:
                        filtered[metric] = measurement[metric]
                measurement = filtered

            measurements.append(measurement)

        return measurements

    def get_heart_rate_samples(
        self,
        start_date: str,
        end_date: str,
        sample_type: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        records = self.db.query_heart_rate_samples(self.user_id, start_date, end_date)

        samples = []
        for record in records:
            if sample_type and record.get("sample_type") != sample_type:
                continue
            samples.append(
                {
                    "timestamp": record["timestamp"],
                    "bpm": record["bpm"],
                    "sample_type": record.get("sample_type", "passive"),
                }
            )

        if limit is not None:
            return samples[:limit]
        return samples

    def get_spo2_samples(
        self,
        start_date: str,
        end_date: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        records = self.db.query_spo2_samples(self.user_id, start_date, end_date)
        samples = [
            {
                "timestamp": record["timestamp"],
                "spo2_pct": record["spo2_pct"],
            }
            for record in records
        ]
        return samples[:limit] if limit is not None else samples

    def get_stress_samples(
        self,
        start_date: str,
        end_date: str,
        level: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        records = self.db.query_stress_samples(self.user_id, start_date, end_date)
        samples = []
        for record in records:
            if level and record.get("level") != level:
                continue
            samples.append(
                {
                    "timestamp": record["timestamp"],
                    "stress_score": record["stress_score"],
                    "level": record["level"],
                }
            )
        return samples[:limit] if limit is not None else samples

    def get_abnormal_heart_beat_events(
        self,
        start_date: str,
        end_date: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        records = self.db.query_abnormal_heart_beat_events(self.user_id, start_date, end_date)
        events = [
            {
                "event_id": record["event_id"],
                "start_at": record["start_at"],
                "end_at": record["end_at"],
                "duration_seconds": record["duration_seconds"],
            }
            for record in records
        ]
        return events[:limit] if limit is not None else events

    def get_data_coverage(self, data_types: list[str] | None = None) -> list[dict[str, Any]]:
        """Get data coverage information."""
        coverage = self.db.get_data_coverage(self.user_id)

        if data_types:
            coverage = [c for c in coverage if c["data_type"] in data_types]

        return coverage
