"""test_cancellation.py
Unit tests for Task Cancellation Manager, Epoch Fencing, and Read-Set Selective Invalidation.
Part of Theme 05: Interruptible Real-Time Agents test suite.
"""
import asyncio
import os
import sys
import unittest

# Ensure src/ is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from clock import VirtualClock
from ledger import CallLedger, CallRecord, CallState
from protocol import ActionType, EventType, InputEvent, OutputAction
from agent import RealTimeAgent
from harness import EvaluationHarness


class TestCancellation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = VirtualClock(start_ms=0)
        self.ledger = CallLedger()

    async def test_epoch_bumping_and_stale_detection(self):
        """Verify that bumping epoch invalidates stale results from older epochs."""
        self.assertEqual(self.ledger.current_epoch, 0)
        
        # Register a call in epoch 0
        call = CallRecord(
            call_id="call_test_01",
            tool_name="flight_search",
            parameters={"destination": "Mumbai", "date": "Tomorrow"},
            read_set={"destination", "date"},
            state=CallState.ISSUED,
            epoch=0
        )
        self.ledger.register_call(call)
        
        # Verify call is registered with current epoch
        self.assertEqual(call.epoch, 0)
        self.assertFalse(self.ledger.is_result_stale("call_test_01", result_epoch=0))
        
        # User interrupts -> bump epoch
        new_epoch = self.ledger.bump_epoch()
        self.assertEqual(new_epoch, 1)
        self.assertEqual(self.ledger.current_epoch, 1)
        
        # Result arriving with old epoch (0) must be detected as stale
        self.assertTrue(self.ledger.is_result_stale("call_test_01", result_epoch=0))

    async def test_read_set_selective_invalidation(self):
        """Verify that only calls whose read_set intersects with changed slots are cancelled."""
        call_flight = CallRecord(
            call_id="call_flight",
            tool_name="flight_search",
            parameters={"destination": "Mumbai", "date": "Tomorrow"},
            read_set={"destination", "date"},
            state=CallState.RUNNING,
        )
        call_weather = CallRecord(
            call_id="call_weather",
            tool_name="weather_lookup",
            parameters={"date": "Tomorrow"},
            read_set={"date"},
            state=CallState.RUNNING,
        )
        self.ledger.register_call(call_flight)
        self.ledger.register_call(call_weather)

        # User changes only 'destination' ("Actually make that Delhi")
        changed_slots = {"destination"}
        cancelled = self.ledger.invalidate_by_read_set(changed_slots)

        # Only call_flight should be cancelled; call_weather should survive!
        cancelled_ids = [c.call_id for c in cancelled]
        self.assertIn("call_flight", cancelled_ids)
        self.assertNotIn("call_weather", cancelled_ids)

        self.assertEqual(call_flight.state, CallState.CANCELLED)
        self.assertEqual(call_weather.state, CallState.RUNNING)

    async def test_end_to_end_interruption_emits_cancel_action(self):
        """End-to-end test: an interruption event promptly emits a CANCEL_CALL action."""
        h = EvaluationHarness()
        manifest_event = (0, InputEvent(
            timestamp_ms=0,
            event_type=EventType.TOOL_MANIFEST,
            session_id="s_cancel",
            payload={"manifests": [{
                "name": "flight_search",
                "description": "Search flights",
                "parameters": {"required": ["destination", "date"]},
                "is_state_modifying": False
            }]}
        ))
        user_query = (50, InputEvent(
            timestamp_ms=50,
            event_type=EventType.TEXT_CHUNK,
            session_id="s_cancel",
            payload={"text": "Find flights to Mumbai tomorrow"},
            is_end_of_turn=True
        ))
        interrupt_event = (150, InputEvent(
            timestamp_ms=150,
            event_type=EventType.INTERRUPTION,
            session_id="s_cancel",
            payload={}
        ))

        timeline = [manifest_event, user_query, interrupt_event]
        result = await h.run_scenario(timeline, settle_extra_ms=300)

        # Check action trace for CANCEL_CALL
        actions = [entry.action for entry in h.trace if entry.kind == "ACTION"]
        cancel_actions = [a for a in actions if a.action_type == ActionType.CANCEL_CALL]
        
        self.assertGreaterEqual(len(cancel_actions), 1, "At least one cancel_call action must be emitted.")
        self.assertEqual(result.interruption_recovery, 100.0, "Interruption recovery score should be 100.0.")


if __name__ == "__main__":
    unittest.main()
