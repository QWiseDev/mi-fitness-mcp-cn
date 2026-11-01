import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx

from deploy.sync_incremental import DATA_TYPES, run_sync


class IncrementalSyncTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.progress = Path(self.directory.name) / "progress.json"
        self.requests = []

    def client(self, results):
        terminal = iter(results)
        polls = 0

        def handle(request):
            nonlocal polls
            if request.method == "POST":
                self.requests.append(json.loads(request.content))
                polls = 0
                return httpx.Response(200, json={"status": "accepted", "sync_id": "test-job"})
            polls += 1
            if polls == 1:
                return httpx.Response(200, json={"status": "running"})
            return httpx.Response(200, json=next(terminal))

        return httpx.Client(base_url="http://test", transport=httpx.MockTransport(handle))

    @staticmethod
    def success():
        return {"status": "ok", "data_types_synced": DATA_TYPES, "records_added": 1}

    @patch("deploy.sync_incremental.time.sleep")
    def test_success_rechecks_recent_days_and_advances_progress(self, sleep):
        with self.client([self.success()]) as client:
            run_sync(client, self.progress, date(2026, 10, 18))
        self.assertEqual(self.requests[0]["start_date"], "2026-10-16")
        self.assertFalse(self.requests[0]["force_full_sync"])
        self.assertEqual(json.loads(self.progress.read_text())["last_successful_end_date"], "2026-10-18")
        sleep.assert_called_once()

    @patch("deploy.sync_incremental.time.sleep")
    def test_downtime_catches_up_in_weeks(self, sleep):
        self.progress.write_text(json.dumps({"last_successful_end_date": "2026-10-01"}))
        with self.client([self.success()] * 3) as client:
            run_sync(client, self.progress, date(2026, 10, 18))
        self.assertEqual(
            [(r["start_date"], r["end_date"]) for r in self.requests],
            [("2026-10-01", "2026-10-07"), ("2026-10-08", "2026-10-14"), ("2026-10-15", "2026-10-18")],
        )

    @patch("deploy.sync_incremental.time.sleep")
    def test_partial_result_does_not_advance_past_failed_week(self, sleep):
        self.progress.write_text(json.dumps({"last_successful_end_date": "2026-10-01"}))
        with self.client([self.success(), {"status": "partial"}]) as client, self.assertRaises(RuntimeError):
            run_sync(client, self.progress, date(2026, 10, 18))
        state = json.loads(self.progress.read_text())
        self.assertEqual(state["status"], "error")
        self.assertEqual(state["last_successful_end_date"], "2026-10-07")
        with self.client([self.success()] * 2) as client:
            run_sync(client, self.progress, date(2026, 10, 18))
        self.assertEqual(self.requests[2]["start_date"], "2026-10-07")

    def test_busy_api_retains_pending_range_for_next_run(self):
        def busy(request):
            return httpx.Response(409, json={"detail": "busy"})

        with httpx.Client(base_url="http://test", transport=httpx.MockTransport(busy)) as client, self.assertRaises(httpx.HTTPStatusError):
            run_sync(client, self.progress, date(2026, 10, 18))
        state = json.loads(self.progress.read_text())
        self.assertNotIn("last_successful_end_date", state)
        self.assertEqual(state["start_date"], "2026-10-16")
        self.assertEqual(state["http_status"], 409)


if __name__ == "__main__":
    unittest.main()
