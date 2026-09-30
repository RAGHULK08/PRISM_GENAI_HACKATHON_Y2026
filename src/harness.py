"""harness.py
Virtual Clock streaming harness, mock tool runner, trace logger, and rubric scorer.
Mirrors the exact scoring weights from the evaluation spec.
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from clock import VirtualClock
from protocol import ActionType, EventType, InputEvent, OutputAction
from agent import RealTimeAgent


# ---------------------------------------------------------------------------
# Rubric weights (must match evaluation spec exactly)
# ---------------------------------------------------------------------------
W_TASK_COMPLETION       = 0.40
W_INTERRUPTION_RECOVERY = 0.35
W_RESPONSE_LATENCY      = 0.15
W_SAFETY_PROTOCOL       = 0.10
MULTIMODAL_MULTIPLIER   = 1.50


@dataclass
class TraceEntry:
    kind:       str          # "EVENT" | "ACTION"
    timestamp:  int
    event:      Optional[InputEvent]  = None
    action:     Optional[OutputAction] = None


@dataclass
class EvaluationResult:
    task_completion:       float = 0.0
    interruption_recovery: float = 0.0
    response_latency:      float = 0.0
    safety_protocol:       float = 0.0
    quality_multiplier:    float = 1.0
    is_multimodal:         bool  = False

    @property
    def weighted_total(self) -> float:
        base = (
            self.task_completion       * W_TASK_COMPLETION +
            self.interruption_recovery * W_INTERRUPTION_RECOVERY +
            self.response_latency      * W_RESPONSE_LATENCY +
            self.safety_protocol       * W_SAFETY_PROTOCOL
        )
        total = base * self.quality_multiplier
        if self.is_multimodal:
            total *= MULTIMODAL_MULTIPLIER
        return total

    def print_table(self, test_name: str) -> None:
        print(f"\n{'?'*54}")
        print(f"  SCORE BREAKDOWN ? {test_name}")
        print(f"{'?'*54}")
        print(f"  Task Completion       : {self.task_completion:>6.1f} / 100")
        print(f"  Interruption Recovery : {self.interruption_recovery:>6.1f} / 100")
        print(f"  Response Latency      : {self.response_latency:>6.1f} / 100")
        print(f"  Safety & Protocol     : {self.safety_protocol:>6.1f} / 100")
        print(f"  Quality Multiplier    : ?{self.quality_multiplier:.2f}")
        if self.is_multimodal:
            print(f"  Multimodal Multiplier : ?{MULTIMODAL_MULTIPLIER:.2f}  ? ACTIVE")
        max_score = 100.0 * (MULTIMODAL_MULTIPLIER if self.is_multimodal else 1.0)
        print(f"{'?'*54}")
        print(f"  WEIGHTED TOTAL        : {self.weighted_total:>6.2f} / {max_score:.0f}  ?")
        print(f"{'?'*54}")


class MockToolEnvironment:
    """Simulates async backend tools with configurable latency and fault injection."""
    def __init__(self, clock: VirtualClock, feedback_queue: asyncio.Queue):
        self.clock          = clock
        self.feedback_queue = feedback_queue
        self._cancelled:    set = set()

    def cancel(self, call_id: str) -> None:
        self._cancelled.add(call_id)

    async def run_tool(
        self,
        call_id:   str,
        tool_name: str,
        args:      Dict[str, Any],
        delay_ms:  int = 400,
        epoch:     int = 0,
    ) -> None:
        await self.clock.sleep_ms(delay_ms)
        if call_id in self._cancelled:
            return
        result = self._mock_result(tool_name, args)
        await self.feedback_queue.put(InputEvent(
            timestamp_ms=self.clock.now_ms(),
            event_type=EventType.TOOL_RESULT,
            session_id="harness",
            payload={"call_id": call_id, "result": result, "epoch": epoch},
        ))

    @staticmethod
    def _mock_result(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "flight_search":
            dest = args.get("destination", "Unknown")
            return {"flights": [{"flight_no": "AI-202", "time": "10:00 AM", "price": 4500, "dest": dest}]}
        if tool_name == "flight_book":
            return {"pnr": "PNR-XYZ789", "status": "CONFIRMED"}
        if tool_name == "manual_lookup":
            return {"solution": "Reset circuit breaker and reboot device."}
        return {"status": "ok"}


class EvaluationHarness:
    """
    Drives a RealTimeAgent through a timeline of events using the VirtualClock.
    Collects all output actions and scores against the rubric.
    """
    def __init__(self):
        self.clock        = VirtualClock(start_ms=0)
        self.input_queue: asyncio.Queue  = asyncio.Queue()
        self.output_queue: asyncio.Queue = asyncio.Queue()
        self.mock_env     = MockToolEnvironment(self.clock, self.input_queue)
        self.agent        = RealTimeAgent(self.clock, self.input_queue, self.output_queue)
        self.trace:       List[TraceEntry] = []
        self._tool_epoch: Dict[str, int]   = {}

    async def run_scenario(
        self,
        timeline:        List[Tuple[int, InputEvent]],
        settle_extra_ms: int = 1200,
        is_multimodal:   bool = False,
    ) -> EvaluationResult:
        agent_task = asyncio.create_task(self.agent.run())

        async def collect_actions():
            while True:
                action = await self.output_queue.get()
                self.trace.append(TraceEntry(
                    kind="ACTION", timestamp=action.timestamp_ms, action=action
                ))
                if action.action_type == ActionType.TOOL_CALL:
                    epoch = self.agent.ledger.current_epoch
                    self._tool_epoch[action.call_id] = epoch
                    asyncio.create_task(self.mock_env.run_tool(
                        action.call_id, action.tool_name,
                        action.parameters or {}, delay_ms=400, epoch=epoch,
                    ))
                elif action.action_type == ActionType.CANCEL_CALL:
                    self.mock_env.cancel(action.call_id)
                self.output_queue.task_done()

        collector_task = asyncio.create_task(collect_actions())

        # Replay timeline
        for event_time, event in sorted(timeline, key=lambda x: x[0]):
            if event_time > self.clock.now_ms():
                self.clock.advance_to(event_time)
            await asyncio.sleep(0)       # Yield to event loop
            self.trace.append(TraceEntry(
                kind="EVENT", timestamp=event_time, event=event
            ))
            await self.input_queue.put(event)
            await asyncio.sleep(0)

        # Advance clock in steps to trigger virtual sleepers (tool latency)
        step_ms = 100
        steps = (settle_extra_ms + 600) // step_ms
        for _ in range(steps):
            self.clock.advance_by(step_ms)
            await asyncio.sleep(0.01)   # real tick to allow coroutines to wake

        agent_task.cancel()
        collector_task.cancel()
        try:
            await agent_task
        except asyncio.CancelledError:
            pass

        result = self._score(is_multimodal=is_multimodal)
        return result

    # ------------------------------------------------------------------
    # Rubric scorer
    # ------------------------------------------------------------------
    def _score(self, is_multimodal: bool) -> EvaluationResult:
        actions = [t.action for t in self.trace if t.kind == "ACTION"]
        events  = [t.event  for t in self.trace if t.kind == "EVENT"]

        result = EvaluationResult(is_multimodal=is_multimodal)

        # --- Safety & Protocol (10%) ---
        # State-modifying tools must not be called more than once with identical args
        state_mod_calls = [a for a in actions if a.action_type == ActionType.TOOL_CALL
                           and a.tool_name in ("flight_book",)]
        keys_seen = set()
        duplicate = False
        for a in state_mod_calls:
            import json, hashlib
            k = hashlib.sha256(
                json.dumps(a.parameters or {}, sort_keys=True).encode()
            ).hexdigest()
            if k in keys_seen:
                duplicate = True
                break
            keys_seen.add(k)
        result.safety_protocol = 0.0 if duplicate else 100.0

        # --- Interruption Recovery (35%) ---
        interruptions = [t for t in self.trace if t.kind == "EVENT"
                         and t.event.event_type == EventType.INTERRUPTION]
        if interruptions:
            cancels = [a for a in actions if a.action_type == ActionType.CANCEL_CALL]
            result.interruption_recovery = 100.0 if cancels else 20.0
        else:
            result.interruption_recovery = 100.0

        # --- Response Latency (15%) ---
        first_text = next(
            (t for t in self.trace if t.kind == "EVENT"
             and t.event.event_type == EventType.TEXT_CHUNK), None
        )
        first_spoken = next(
            (t for t in self.trace if t.kind == "ACTION"
             and t.action.action_type in (ActionType.SPOKEN_FILLER, ActionType.CLARIFICATION)), None
        )
        if first_text and first_spoken:
            latency = first_spoken.timestamp - first_text.timestamp
            if   latency <= 10:   result.response_latency = 100.0
            elif latency <= 100:  result.response_latency = 95.0
            elif latency <= 300:  result.response_latency = 85.0
            elif latency <= 800:  result.response_latency = 60.0
            else:                 result.response_latency = 30.0
        else:
            result.response_latency = 50.0

        # --- Task Completion (40%) ---
        final_responses = [a for a in actions if a.action_type == ActionType.FINAL_RESPONSE]
        if final_responses:
            last = final_responses[-1]
            text = (last.text_content or "").lower()
            # Penalise false completion language before ledger confirmation
            false_claims = any(w in text for w in ("done", "i have booked", "already reserved"))
            result.task_completion = 80.0 if false_claims else 100.0
        else:
            result.task_completion = 30.0

        # --- Quality multiplier ---
        # Check for no false completion claims + truthful ack
        filler_texts = [a.text_content or "" for a in actions if a.action_type == ActionType.SPOKEN_FILLER]
        false_fillers = any(w in t.lower() for t in filler_texts for w in ("done", "booked", "confirmed"))
        result.quality_multiplier = 1.05 if not false_fillers else 0.85

        return result
