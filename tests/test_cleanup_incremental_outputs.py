import os
import tempfile
import time
import unittest
from pathlib import Path

from tools.cleanup_incremental_outputs import (
    iter_debug_candidates,
    iter_experiment_candidates,
    utc_now,
)


class CleanupIncrementalOutputsTests(unittest.TestCase):
    def test_iter_debug_candidates_reports_old_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            traces = root / "agentic_traces"
            traces.mkdir()
            target = traces / "old.agentic_trace.json"
            target.write_text("{}", encoding="utf-8")
            old_time = time.time() - 10 * 24 * 3600
            os.utime(target, (old_time, old_time))

            candidates = iter_debug_candidates(root, cutoff=utc_now())

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].path.name, "old.agentic_trace.json")

    def test_iter_experiment_candidates_reports_old_phase_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            experiment = root / "phase5-agentic-retest-state.json"
            experiment.write_text("{}", encoding="utf-8")
            old_time = time.time() - 10 * 24 * 3600
            os.utime(experiment, (old_time, old_time))

            candidates = iter_experiment_candidates(root, cutoff=utc_now())

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].path.name, "phase5-agentic-retest-state.json")


if __name__ == "__main__":
    unittest.main()
