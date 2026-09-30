"""test_idempotency.py
Unit tests for Two-Phase Idempotency Barrier and Tool Safety.
Part of Theme 05: Interruptible Real-Time Agents test suite.
"""
import os
import sys
import unittest

# Ensure src/ is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from tool_gate import ToolManifest, ToolRegistry


class TestIdempotency(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.manifests = [
            {
                "name": "flight_search",
                "description": "Searches flights",
                "parameters": {"required": ["destination", "date"]},
                "is_state_modifying": False
            },
            {
                "name": "flight_book",
                "description": "Reserves and purchases flight ticket",
                "parameters": {"required": ["flight_id", "passenger_name"]},
                "is_state_modifying": True
            }
        ]
        self.registry.parse_manifests(self.manifests)

    def test_tool_classification(self):
        """Verify read-only vs state-modifying classification from manifest."""
        search = self.registry.get("flight_search")
        book = self.registry.get("flight_book")

        self.assertIsNotNone(search)
        self.assertIsNotNone(book)
        self.assertFalse(search.is_state_modifying)
        self.assertTrue(book.is_state_modifying)

    def test_read_only_speculative_execution_allowed_on_partial_turn(self):
        """Read-only tools must be allowed to run speculatively before end-of-turn."""
        args = {"destination": "Delhi", "date": "Friday"}
        confidences = {"destination": 0.95, "date": 0.95}

        # is_end_of_turn=False
        allowed, key = self.registry.can_execute(
            tool_name="flight_search",
            args=args,
            is_end_of_turn=False,
            slot_confidences=confidences
        )
        self.assertTrue(allowed, "Read-only tools should be allowed to run speculatively.")
        self.assertTrue(len(key) > 0)

    def test_state_modifying_tool_gated_on_partial_turn(self):
        """State-modifying tools must NOT execute until end-of-turn is explicitly seen."""
        args = {"flight_id": "AI-202", "passenger_name": "Raghul"}
        confidences = {"flight_id": 0.95, "passenger_name": 0.95}

        # When turn has NOT ended (is_end_of_turn=False)
        allowed, reason = self.registry.can_execute(
            tool_name="flight_book",
            args=args,
            is_end_of_turn=False,
            slot_confidences=confidences
        )
        self.assertFalse(allowed, "State-modifying tool must be gated on partial turn.")
        self.assertIn("end_of_turn", reason)

        # When end_of_turn is observed
        allowed_eot, key = self.registry.can_execute(
            tool_name="flight_book",
            args=args,
            is_end_of_turn=True,
            slot_confidences=confidences
        )
        self.assertTrue(allowed_eot, "State-modifying tool should be allowed when turn ends.")

    def test_confidence_threshold_gating(self):
        """Tools should be blocked if any required slot confidence falls below 0.80."""
        args = {"destination": "Delhi", "date": "Friday"}
        low_confidences = {"destination": 0.50, "date": 0.95}

        allowed, reason = self.registry.can_execute(
            tool_name="flight_search",
            args=args,
            is_end_of_turn=True,
            slot_confidences=low_confidences
        )
        self.assertFalse(allowed)
        self.assertIn("confidence", reason.lower())

    def test_duplicate_prevention_via_idempotency_key(self):
        """Verify that duplicate executions of state-modifying actions are blocked."""
        args = {"flight_id": "AI-202", "passenger_name": "Raghul"}
        confidences = {"flight_id": 0.99, "passenger_name": 0.99}

        # First commit attempt -> Allowed
        allowed_1, key_1 = self.registry.can_execute(
            tool_name="flight_book",
            args=args,
            is_end_of_turn=True,
            slot_confidences=confidences
        )
        self.assertTrue(allowed_1)
        self.registry.record_commit(key_1)

        # Second attempt with identical arguments -> BLOCKED by Idempotency Gate
        allowed_2, reason_2 = self.registry.can_execute(
            tool_name="flight_book",
            args=args,
            is_end_of_turn=True,
            slot_confidences=confidences
        )
        self.assertFalse(allowed_2, "Identical state-modifying call must be blocked.")
        self.assertIn("idempotency gate", reason_2.lower())

        # Attempt with different arguments (different flight or passenger) -> ALLOWED
        different_args = {"flight_id": "AI-999", "passenger_name": "Raghul"}
        allowed_3, key_3 = self.registry.can_execute(
            tool_name="flight_book",
            args=different_args,
            is_end_of_turn=True,
            slot_confidences=confidences
        )
        self.assertTrue(allowed_3, "Call with different arguments should have a distinct key and be allowed.")
        self.assertNotEqual(key_1, key_3)


if __name__ == "__main__":
    unittest.main()
