import os
import tempfile
import time
import unittest
from pathlib import Path

from tools.maintenance_retention import RetentionPolicy, run_maintenance


class MaintenanceRetentionTests(unittest.TestCase):
    def test_run_maintenance_writes_report_and_keeps_dry_run_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "orbika_incremental"
            runtime_dir = Path(tmpdir) / "launcher"
            traces = root / "agentic_traces"
            traces.mkdir(parents=True)
            runtime_dir.mkdir(parents=True)

            stale_trace = traces / "old.agentic_trace.json"
            stale_trace.write_text("{}", encoding="utf-8")
            old_time = time.time() - 10 * 24 * 3600
            os.utime(stale_trace, (old_time, old_time))

            report_file = runtime_dir / "maintenance.json"
            report = run_maintenance(
                root=root,
                runtime_dir=runtime_dir,
                report_file=report_file,
                policy=RetentionPolicy(debug_retention_days=7, experiment_retention_days=7),
                apply=False,
                database_url=None,
            )

            self.assertEqual(report["status"], "dry-run")
            self.assertTrue(report_file.exists())
            self.assertGreaterEqual(report["local"]["candidate_count"], 1)
            self.assertEqual(report["summary"]["local_deleted"], 0)
            self.assertFalse(report["summary"]["database_enabled"])


if __name__ == "__main__":
    unittest.main()