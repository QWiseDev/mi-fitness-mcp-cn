import pytest

from mi_fitness_mcp.adapters.mi_fitness_cloud import (
    MiFitnessCloudAdapter,
    _is_authentication_error,
)


async def _collect(async_iterable):
    items = []
    async for item in async_iterable:
        items.append(item)
    return items


def test_optional_number_helpers():
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    assert adapter._optional_float(0) is None
    assert adapter._optional_float("1.5") == 1.5
    assert adapter._optional_int(0) is None
    assert adapter._optional_int("7") == 7


def test_parse_value_dict_and_json():
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    assert adapter._parse_value({"value": {"steps": 1}}) == {"steps": 1}
    assert adapter._parse_value({"value": '{"steps": 2}'}) == {"steps": 2}


def test_record_datetime_uses_zone_offset():
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    dt = adapter._record_datetime({"time": 0, "zone_offset": 10800})
    assert dt.isoformat().startswith("1970-01-01T03:00:00")


@pytest.mark.asyncio
async def test_iter_daily_activity_aggregates_steps_and_calories(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    adapter._connected = True
    adapter._client = object()

    async def fake_fetch(key, start_date, end_date, region=None):
        if key == "steps":
            return [
                {
                    "time": 1743467400,
                    "zone_offset": 0,
                    "value": '{"steps": 10, "distance": 8, "calories": 1}',
                },
                {
                    "time": 1743467460,
                    "zone_offset": 0,
                    "value": '{"steps": 20, "distance": 16, "calories": 2}',
                },
            ]
        if key == "calories":
            return [
                {"time": 1743467400, "zone_offset": 0, "value": '{"calories": 5}'},
                {"time": 1743467460, "zone_offset": 0, "value": '{"calories": 7}'},
            ]
        return []

    monkeypatch.setattr(adapter, "_fetch_key", fake_fetch)
    items = await _collect(adapter.iter_daily_activity("2025-04-01", "2025-04-01"))

    assert len(items) == 1
    assert items[0].steps == 30
    assert items[0].distance_m == 24
    assert items[0].active_kcal == 12


@pytest.mark.asyncio
async def test_fetch_key_rejects_repeated_pagination_cursor(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1", region="cn")
    adapter._client = object()

    async def fake_request(base_url, api_path, payload):
        return {"data_list": [], "has_more": True, "next_key": "same"}

    monkeypatch.setattr(adapter, "_request", fake_request)
    with pytest.raises(RuntimeError, match="cursor loop"):
        await adapter._fetch_key("steps", "2026-07-06", "2026-07-12")


@pytest.mark.asyncio
async def test_connect_failure_closes_client(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="bad", region="cn")

    async def failed_login(user_id, pass_token):
        raise RuntimeError("invalid credentials")

    monkeypatch.setattr(adapter, "_login_with_token", failed_login)
    assert await adapter.connect() is False
    assert adapter._client is None
    assert "invalid credentials" in adapter.last_error


def test_authentication_error_detection():
    assert _is_authentication_error(401, "denied")
    assert _is_authentication_error(0, "session expired")
    assert _is_authentication_error(-10001, "unknown")
    assert not _is_authentication_error(500, "temporary server failure")


@pytest.mark.asyncio
async def test_iter_sleep_sessions_stage_mapping_and_awake_duration(monkeypatch):
    """分期编码 2=deep / 3=light / 4=rem / 5=awake。

    由真实账号数据对账得出：items 分段直方图与顶层 sleep_deep/light/rem/
    awake_duration 聚合逐夜吻合；此前映射为猜测值，把 deep 错标成 light、
    rem/awake 互换。
    """
    import json

    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    adapter._connected = True
    adapter._client = object()

    raw_value = json.dumps(
        {
            "bedtime": 1795100040,
            "wake_up_time": 1795128180,
            "duration": 414,
            "sleep_awake_duration": 55,
            "sleep_deep_duration": 74,
            "sleep_light_duration": 215,
            "sleep_rem_duration": 125,
            "sleep_efficiency": 82,
            "awake_count": 2,
            "avg_hr": 67,
            "max_hr": 88,
            "min_hr": 59,
            "avg_spo2": 95,
            "max_spo2": 99,
            "min_spo2": 91,
            "avg_breath": 16,
            "avg_hrv": 41,
            "max_hrv": 55,
            "min_hrv": 18,
            "items": [
                {"start_time": 1795100040, "end_time": 1795100460, "state": 2},
                {"start_time": 1795100460, "end_time": 1795101000, "state": 3},
                {"start_time": 1795101000, "end_time": 1795101120, "state": 4},
                {"start_time": 1795101120, "end_time": 1795101200, "state": 5},
                {"start_time": 1795101200, "end_time": 1795101300, "state": 9},
            ],
        }
    )

    async def fake_fetch(key, start_date, end_date, region=None):
        return [{"time": 1795128180, "zone_offset": 28800, "value": raw_value}]

    monkeypatch.setattr(adapter, "_fetch_key", fake_fetch)

    sessions = await _collect(adapter.iter_sleep_sessions("2026-11-18", "2026-11-21"))
    assert len(sessions) == 1
    session = sessions[0]
    # duration 是入睡分钟（deep+light+rem），不再减去清醒分钟造成重复扣减
    assert session.time_asleep_minutes == 414
    assert session.time_awake_minutes == 55
    by_stage = {}
    for stage in session.stages:
        by_stage[stage.stage] = by_stage.get(stage.stage, 0) + stage.minutes
    assert by_stage == {"deep": 7, "light": 10, "rem": 2, "awake": 1}
    assert session.sleep_efficiency == 82
    assert session.awake_count == 2
    assert session.avg_hr == 67
    assert session.avg_spo2 == 95
    assert session.avg_breath == 16
    assert session.avg_hrv == 41
    assert session.raw_payload["bedtime"] == 1795100040


@pytest.mark.asyncio
async def test_iter_sleep_sessions_merges_overlapping_fragments(monkeypatch):
    """云端把一夜拆成多条重叠碎片（App 端 sleep_segment 表同样分片）。

    用 2026-11-19/20 夜的真实结构：主记录 22:54-06:43（含 55 分钟清醒）+
    22:54-23:19 与 00:11-01:44 两个碎片（都落在主记录区间内），外加前一晚
    375 分钟与后一晚 437 分钟两条完整记录 → 合并后应恰好 3 夜，每组保留
    覆盖最宽的代表；白天开始的会话标记为小睡。
    """
    import json

    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    adapter._connected = True
    adapter._client = object()

    def record(bedtime, wake, duration, awake, items=True):
        payload = {
            "bedtime": bedtime,
            "wake_up_time": wake,
            "duration": duration,
            "sleep_awake_duration": awake,
        }
        if items:
            payload["items"] = [
                {"start_time": bedtime, "end_time": bedtime + duration * 60, "state": 3}
            ]
        return {
            "time": wake,
            "zone_offset": 28800,
            "zone_name": "Asia/Shanghai",
            "value": json.dumps(payload),
        }

    raw_records = [
        record(1795100040, 1795101540, 25, 0),  # 碎片：22:54-23:19
        record(1795104660, 1795110240, 93, 0),  # 碎片：00:11-01:44（在主夜区间内）
        record(1795100040, 1795128180, 414, 55),  # 主夜：22:54-06:43
        record(1795013820, 1795036320, 375, 0),  # 前一晚：22:57-05:12
        record(1795154400, 1795156200, 30, 0),  # 白天 14:00-14:30 → 小睡
    ]

    async def fake_fetch(key, start_date, end_date, region=None):
        return raw_records

    monkeypatch.setattr(adapter, "_fetch_key", fake_fetch)

    sessions = await _collect(adapter.iter_sleep_sessions("2026-11-18", "2026-11-21"))
    assert len(sessions) == 3
    by_start = {str(s.start_at): s for s in sessions}
    main = by_start["2026-11-19 22:54:00+08:00"]
    assert main.duration_minutes == 414
    assert main.time_awake_minutes == 55
    assert main.is_nap is False
    assert by_start["2026-11-18 22:57:00+08:00"].duration_minutes == 375
    nap = by_start["2026-11-20 14:00:00+08:00"]
    assert nap.duration_minutes == 30
    assert nap.is_nap is True
