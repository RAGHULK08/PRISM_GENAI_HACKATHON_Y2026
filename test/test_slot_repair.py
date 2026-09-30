"""test_slot_repair.py
Unit tests for Differential Slot Engine and Conversational Self-Repair.
Part of Theme 05: Interruptible Real-Time Agents test suite.
"""
import os
import sys
import unittest

# Ensure src/ is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from slot_store import DifferentialSlotEngine


class TestSlotRepair(unittest.TestCase):
    def setUp(self):
        self.engine = DifferentialSlotEngine()

    def test_initial_slot_assignment_and_versioning(self):
        """Slots start at version 1 and record confidence and timestamp."""
        v = self.engine.set_slot("destination", "Mumbai", confidence=0.95, timestamp_ms=100)
        self.assertEqual(v, 1)

        snapshot = self.engine.get_snapshot()
        self.assertEqual(snapshot["destination"], "Mumbai")

        # Second update to same slot increments version to 2
        v2 = self.engine.set_slot("destination", "Delhi", confidence=0.98, timestamp_ms=200)
        self.assertEqual(v2, 2)
        self.assertEqual(self.engine.get_snapshot()["destination"], "Delhi")

    def test_self_repair_edit_markers_detection(self):
        """Test recognition of various conversational pivots in natural speech."""
        phrases = [
            ("Mumbai, no wait, Delhi", "Delhi"),
            ("Book for tomorrow actually Friday", "Friday"),
            ("Fly to London, scratch that, Paris", "Paris"),
            ("Book AI-101, make that AI-202", "AI-202"),
            ("Reserve for John, i mean, Johnny", "Johnny"),
        ]

        for full_text, expected_tail in phrases:
            repaired = self.engine.parse_self_repair(full_text)
            self.assertIsNotNone(repaired, f"Failed to match edit marker in '{full_text}'")
            self.assertEqual(repaired, expected_tail)

        # Non-repair text should return None
        no_repair = self.engine.parse_self_repair("Find flights to Mumbai for tomorrow")
        self.assertIsNone(no_repair)

    def test_localized_slot_correction_preserves_other_slots(self):
        """Verify that correcting one slot preserves valid pre-existing slots."""
        # Initial turn: user specifies destination and date
        self.engine.update_deltas({"destination": "Mumbai", "date": "Friday"}, confidence=0.95, timestamp_ms=100)
        snapshot = self.engine.get_snapshot()
        self.assertEqual(snapshot["destination"], "Mumbai")
        self.assertEqual(snapshot["date"], "Friday")

        # User self-repairs: "Actually make that Delhi"
        changed = self.engine.update_deltas({"destination": "Delhi"}, confidence=0.98, timestamp_ms=250)

        # Only destination should be in changed set
        self.assertEqual(changed, {"destination"})

        # Final snapshot must have updated destination, while date is still intact!
        updated_snapshot = self.engine.get_snapshot()
        self.assertEqual(updated_snapshot["destination"], "Delhi")
        self.assertEqual(updated_snapshot["date"], "Friday", "Date slot must be preserved across localized repair.")

    def test_multi_turn_tracking_and_clear(self):
        """Verify turn bumping and reset functionality."""
        self.engine.set_slot("seat_class", "Economy", confidence=0.9, timestamp_ms=100)
        self.assertEqual(self.engine._slots["seat_class"].turn_id, 1)

        self.engine.bump_turn()
        self.engine.set_slot("meal", "Vegetarian", confidence=0.9, timestamp_ms=300)
        self.assertEqual(self.engine._slots["meal"].turn_id, 2)

        # Clear session resets state
        self.engine.clear()
        self.assertEqual(len(self.engine.get_snapshot()), 0)
        self.assertIsNone(self.engine.intent)


if __name__ == "__main__":
    unittest.main()
