"""通过本机 API 定期同步，保留成功日期并重查最近三天。"""

import fcntl
import json
import os
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

STATE_DIR = Path("/var/lib/mi-fitness-mcp")
DATABASE = STATE_DIR / "data/mi-fitness-mcp/mi_fitness.db"
PROGRESS = STATE_DIR / "incremental-sync.json"
OVERLAP_DAYS = 3
CHUNK_DAYS = 7
DATA_TYPES = [
    "daily_activity", "heart_rate", "sleep", "workouts",
    "body_measurements", "spo2", "stress", "abnormal_heart_beat",
]


def save_progress(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def run_sync(client, progress, today):
    state = json.loads(progress.read_text()) if progress.exists() else {}
    overlap_start = today - timedelta(days=OVERLAP_DAYS - 1)
    previous = state.get("last_successful_end_date") or state.get("start_date")
    cursor = min(date.fromisoformat(previous), overlap_start) if previous else overlap_start
    try:
        while cursor <= today:
            end = min(cursor + timedelta(days=CHUNK_DAYS - 1), today)
            state.update(
                status="running", start_date=cursor.isoformat(), end_date=end.isoformat(),
                attempted_at=datetime.now(UTC).isoformat(),
            )
            state.pop("error", None)
            state.pop("http_status", None)
            state.pop("sync_id", None)
            state.pop("results", None)
            state.pop("records_processed", None)
            save_progress(progress, state)
            response = client.post("/api/sync", json={
                "data_types": DATA_TYPES,
                "start_date": cursor.isoformat(),
                "end_date": end.isoformat(),
                "force_full_sync": False,
                "background": True,
            })
            response.raise_for_status()
            state["sync_id"] = response.json()["sync_id"]
            save_progress(progress, state)
            while True:
                response = client.get("/api/sync/" + state["sync_id"])
                response.raise_for_status()
                result = response.json()
                if result["status"] not in {"queued", "running"}:
                    break
                time.sleep(2)
            state["results"] = [
                {key: item[key] for key in ("data_type", "status", "added", "updated", "skipped") if key in item}
                for item in result.get("results", [])
            ]
            if result["status"] != "ok" or set(result.get("data_types_synced", [])) != set(DATA_TYPES):
                raise RuntimeError("同步未全部成功")
            state.update(
                status="ok", last_successful_end_date=end.isoformat(),
                finished_at=datetime.now(UTC).isoformat(),
                records_processed=result.get("records_added", 0) + result.get("records_updated", 0),
            )
            save_progress(progress, state)
            print(json.dumps(state, ensure_ascii=False), flush=True)
            cursor = end + timedelta(days=1)
    except (httpx.HTTPError, RuntimeError) as exc:
        state.update(status="error", error=type(exc).__name__, finished_at=datetime.now(UTC).isoformat())
        if isinstance(exc, httpx.HTTPStatusError):
            state["http_status"] = exc.response.status_code
        save_progress(progress, state)
        raise


def main():
    os.umask(0o077)
    with (STATE_DIR / "incremental-sync.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            accounts = connection.execute(
                "SELECT key,user_id FROM api_keys WHERE revoked=0 ORDER BY created_at DESC"
            ).fetchall()
        if not accounts or len({row["user_id"] for row in accounts}) != 1:
            raise RuntimeError("定时同步需要唯一有效的扫码账号")
        with httpx.Client(
            base_url="http://127.0.0.1:8321", headers={"X-API-Key": accounts[0]["key"]},
            timeout=30, trust_env=False,
        ) as client:
            run_sync(client, PROGRESS, datetime.now(ZoneInfo("Asia/Shanghai")).date())


if __name__ == "__main__":
    try:
        main()
    except (httpx.HTTPError, RuntimeError) as error:
        # 不输出 HTTP 请求头或响应原文，避免将凭据写入日志。
        print(json.dumps({"status": "error", "error": type(error).__name__}), flush=True)
        raise SystemExit(1) from None
