"""2026-10-18 全历史同步任务：探测云端年份，通过现有 API 分周同步并保存进度。"""

import asyncio
import fcntl
import hashlib
import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter

STATE_DIR = Path("/var/lib/mi-fitness-mcp")
DATABASE = STATE_DIR / "data/mi-fitness-mcp/mi_fitness.db"
PROGRESS = STATE_DIR / "history-sync-20261018.json"
END_DATE = date(2026, 10, 18)
FITNESS_KEYS = {
    "daily_activity": ["steps", "calories"],
    "heart_rate": ["heart_rate", "resting_heart_rate"],
    "sleep": ["sleep"],
    "body_measurements": ["weight"],
    "spo2": ["spo2"],
    "stress": ["stress"],
    "abnormal_heart_beat": ["abnormal_heart_beat"],
    "workouts": [None],
}


def save(state):
    temporary = PROGRESS.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(PROGRESS)


def weeks(first, last):
    cursor = first - timedelta(days=first.weekday())
    while cursor <= last:
        yield max(cursor, first), min(cursor + timedelta(days=6), last, END_DATE)
        cursor += timedelta(days=7)


async def discover(adapter):
    plan = set()
    discovery = []

    async def page(key, first, last):
        if first is None:
            start_time = 0
        else:
            start_time, _ = adapter._date_range_to_timestamps(first.isoformat(), last.isoformat())
        _, end_time = adapter._date_range_to_timestamps(last.isoformat(), last.isoformat())
        if key is None:
            path = "/app/v1/data/get_sport_records_by_time"
            payload = {"start_time": start_time, "end_time": end_time, "limit": 50}
            list_key = "sport_records"
        else:
            path = "/app/v1/data/get_fitness_data_by_time"
            payload = {"start_time": start_time, "end_time": end_time, "key": key}
            list_key = "data_list"
        result = await adapter._request("https://hlth.io.mi.com", path, payload)
        dates = [
            datetime.fromtimestamp(int(item["time"]), tz=adapter._request_timezone()).date()
            for item in result.get(list_key, [])
        ]
        return dates, bool(result.get("has_more"))

    def add_record_weeks(data_type, dates):
        for day in dates:
            for first, last in weeks(day - timedelta(days=day.weekday()), day - timedelta(days=day.weekday()) + timedelta(days=6)):
                plan.add((first.isoformat(), last.isoformat(), data_type))

    for data_type, keys in FITNESS_KEYS.items():
        for key in keys:
            dates, has_more = await page(key, None, END_DATE)
            item = {"data_type": data_type, "cloud_key": key or "workouts", "first_page_count": len(dates), "has_more": has_more, "first_date": min(dates).isoformat() if dates else None}
            discovery.append(item)
            print("DISCOVERY", json.dumps(item, ensure_ascii=False), flush=True)
            if not dates:
                continue
            if not has_more:
                add_record_weeks(data_type, dates)
                continue
            for year in range(min(dates).year, END_DATE.year + 1):
                first = date(year, 1, 1)
                last = min(date(year, 12, 31), END_DATE)
                year_dates, year_has_more = await page(key, first, last)
                if year_has_more:
                    for start, end in weeks(first, last):
                        plan.add((start.isoformat(), end.isoformat(), data_type))
                else:
                    add_record_weeks(data_type, year_dates)
    return [{"start_date": first, "end_date": last, "data_type": kind, "status": "pending"} for first, last, kind in sorted(plan)], discovery


async def main():
    os.umask(0o077)
    with sqlite3.connect(DATABASE) as connection:
        connection.row_factory = sqlite3.Row
        accounts = connection.execute("SELECT key,user_id,pass_token,region FROM api_keys WHERE revoked=0 ORDER BY created_at DESC").fetchall()
        assert accounts and len({row["user_id"] for row in accounts}) == 1, "需要唯一有效账号"
        account = accounts[0]
        backup = STATE_DIR / "backups/before-full-history-20261018.db"
        backup.parent.mkdir(mode=0o700, exist_ok=True)
        if not backup.exists():
            with sqlite3.connect(backup) as target:
                connection.backup(target)
    account_hash = hashlib.sha256(account["user_id"].encode()).hexdigest()[:16]
    if PROGRESS.exists():
        state = json.loads(PROGRESS.read_text())
        assert state["account_hash"] == account_hash, "进度文件属于其他账号"
    else:
        adapter = MiFitnessCloudAdapter(user_id=account["user_id"], pass_token=account["pass_token"], region=account["region"])
        assert await adapter.connect(), "小米云登录失败"
        try:
            jobs, discovery = await discover(adapter)
        finally:
            await adapter.close()
        state = {"account_hash": account_hash, "end_date": END_DATE.isoformat(), "status": "running", "discovery": discovery, "jobs": jobs}
        save(state)
    state["status"] = "running"
    save(state)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8321", headers={"X-API-Key": account["key"]}, timeout=240, trust_env=False) as client:
        for index, job in enumerate(state["jobs"]):
            if job["status"] == "ok":
                continue
            state["current"] = {"index": index + 1, **job}
            save(state)
            attempts = 0
            while attempts < 3:
                try:
                    response = await client.post("/api/sync", json={"data_types": [job["data_type"]], "start_date": job["start_date"], "end_date": job["end_date"], "force_full_sync": True})
                    if response.status_code == 409:
                        await asyncio.sleep(3)
                        continue
                    response.raise_for_status()
                    result = response.json()
                    job["status"] = result.get("status", "error")
                    job["processed"] = result.get("records_added", 0) + result.get("records_updated", 0)
                    if job["status"] == "ok":
                        job.pop("error", None)
                        break
                    job["error"] = "API returned " + job["status"]
                except httpx.HTTPError as exc:
                    job["status"] = "error"
                    job["error"] = type(exc).__name__
                attempts += 1
                await asyncio.sleep(attempts * 2)
            save(state)
            if (index + 1) % 10 == 0 or job["status"] != "ok":
                print("PROGRESS", json.dumps({"done": sum(j["status"] == "ok" for j in state["jobs"]), "total": len(state["jobs"]), "job": job}, ensure_ascii=False), flush=True)
    state.pop("current", None)
    state["status"] = "complete" if all(job["status"] == "ok" for job in state["jobs"]) else "partial"
    save(state)
    print("FINISHED", json.dumps({"status": state["status"], "total": len(state["jobs"]), "failed": sum(job["status"] != "ok" for job in state["jobs"])}, ensure_ascii=False), flush=True)
    if state["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    with (STATE_DIR / "history-sync.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        asyncio.run(main())
