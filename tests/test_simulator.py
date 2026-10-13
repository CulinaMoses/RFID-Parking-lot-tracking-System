import unittest

from app.simulator import SimParams, run_all


class TestSimulator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = {r["scenario"]: r for r in run_all(SimParams())}

    def test_deterministic_for_same_seed(self):
        again = {r["scenario"]: r for r in run_all(SimParams())}
        self.assertEqual(self.rows, again)

    def test_decisions_always_correct_when_tag_read(self):
        for r in self.rows.values():
            if r["decision_correct_pct"] is not None:
                self.assertEqual(r["decision_correct_pct"], 100.0, r["scenario"])

    def test_no_events_lost_even_when_offline(self):
        for name, r in self.rows.items():
            if "no power" not in name:
                self.assertEqual(r["unrecorded"], 0, name)
        self.assertGreater(self.rows["UHF 3.7 m, server offline"]["buffered_then_synced"], 0)

    def test_occupancy_matches_after_sync(self):
        for r in self.rows.values():
            self.assertEqual(r["vehicles_inside_per_lot_count"], r["vehicles_inside_per_simulator"], r["scenario"])

    def test_range_limits(self):
        self.assertEqual(self.rows["HF 1.0 m, online"]["read_accuracy_pct"], 0.0)
        self.assertGreaterEqual(self.rows["UHF 6.0 m, online"]["read_accuracy_pct"], 98.0)
        self.assertLess(self.rows["UHF 8.0 m, online"]["read_accuracy_pct"], 98.0)
        self.assertEqual(self.rows["UHF 3.7 m, no power"]["unrecorded"], 100)

    def test_offline_decisions_are_faster(self):
        self.assertLess(self.rows["UHF 3.7 m, server offline"]["processing_mean_s"],
                        self.rows["UHF 3.7 m, online"]["processing_mean_s"])


if __name__ == "__main__":
    unittest.main()
