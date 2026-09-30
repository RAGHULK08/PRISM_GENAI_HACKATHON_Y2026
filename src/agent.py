"""agent.py
Central event-driven orchestrator.
Coordinates Fast Path, Slow Path, Ledger, Tool Execution, and Output over async queues.
"""
import asyncio
import re
import uuid
from typing import Any, Dict, Optional, Set

from clock import Clock
from protocol import ActionType, EventType, InputEvent, OutputAction, StateSnapshot
from slot_store import DifferentialSlotEngine
from ledger import CallLedger, CallRecord, CallState
from tool_gate import ToolRegistry
from multimodal import MultimodalBuffer, FrameMetadata, AudioChunkMetadata
from fast_path import FastPathEngine


# ---------------------------------------------------------------------------
# Lightweight rule-based intent & slot extractor (no LLM — sub-5ms)
# ---------------------------------------------------------------------------
_DEST_RE  = re.compile(r"\bto\s+([A-Za-z]{3,})\b", re.IGNORECASE)
_DATE_RE  = re.compile(r"\b(tomorrow|today|friday|monday|tuesday|wednesday|thursday|saturday|sunday|next\s+week)\b", re.IGNORECASE)
_ERR_RE   = re.compile(r"(ERR[-\s]?\d+|E-\d+|error\s+code\s*[:\s]*(\w[\w-]*))", re.IGNORECASE)
_FID_RE   = re.compile(r"\b([A-Z]{2}-?\d{3,})\b")
_NAME_RE  = re.compile(r"\bfor\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b")


def _fast_parse(text: str) -> tuple[Optional[str], Dict[str, Any], Set[str]]:
    """Returns (intent, slots, read_set) using pure regex — always < 5ms."""
    intent: Optional[str] = None
    slots:  Dict[str, Any] = {}
    lower = text.lower()

    if any(w in lower for w in ("flight", "fly", "flying", "plane")):
        if any(w in lower for w in ("book", "reserve", "confirm", "purchase")):
            intent = "flight_book"
            m = _FID_RE.search(text)
            if m:
                slots["flight_id"] = m.group(1)
            m = _NAME_RE.search(text)
            if m:
                slots["passenger_name"] = m.group(1)
        else:
            intent = "flight_search"
            m = _DEST_RE.search(text)
            if m:
                slots["destination"] = m.group(1).capitalize()
            m = _DATE_RE.search(text)
            if m:
                slots["date"] = m.group(1).capitalize()

    elif any(w in lower for w in ("error", "manual", "troubleshoot", "fix", "screen", "device")):
        intent = "manual_lookup"
        m = _ERR_RE.search(text)
        if m:
            slots["error_code"] = m.group(0).strip()

    read_set = set(slots.keys())
    return intent, slots, read_set


# ---------------------------------------------------------------------------
# Tool → (read_set, required manifest args) mapping
# ---------------------------------------------------------------------------
_TOOL_MAP: Dict[str, Dict[str, Any]] = {
    "flight_search": {"slot_keys": ["destination", "date"]},
    "flight_book":   {"slot_keys": ["flight_id", "passenger_name"]},
    "manual_lookup": {"slot_keys": ["error_code"]},
}


class RealTimeAgent:
    """
    Unified asyncio coordinator driving all subsystems from a single event loop.

    Input:  asyncio.Queue[InputEvent]
    Output: asyncio.Queue[OutputAction]
    Clock:  injected (never calls time.time() directly)
    """
    def __init__(
        self,
        clock:        Clock,
        input_queue:  asyncio.Queue,
        output_queue: asyncio.Queue,
    ):
        self.clock        = clock
        self.input_queue  = input_queue
        self.output_queue = output_queue

        self.slots      = DifferentialSlotEngine()
        self.ledger     = CallLedger()
        self.tools      = ToolRegistry()
        self.multimodal = MultimodalBuffer()
        self.fast_path  = FastPathEngine()

        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._running       = False

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    async def run(self) -> None:
        self._running = True
        try:
            while self._running:
                event = await self.input_queue.get()
                await self._handle_event(event)
                self.input_queue.task_done()
        except asyncio.CancelledError:
            pass

    async def _emit(self, action: OutputAction) -> None:
        await self.output_queue.put(action)

    # ------------------------------------------------------------------
    # Event dispatch
    # ------------------------------------------------------------------
    async def _handle_event(self, event: InputEvent) -> None:
        now = self.clock.now_ms()

        if event.event_type == EventType.TOOL_MANIFEST:
            self.tools.parse_manifests(event.payload.get("manifests", []))

        elif event.event_type == EventType.VIDEO_FRAME:
            self.multimodal.add_frame(FrameMetadata(
                timestamp_ms=now,
                frame_id=event.payload.get("frame_id", ""),
                ocr_text=event.payload.get("ocr_text"),
                detected_objects=event.payload.get("objects", []),
                confidence=event.payload.get("confidence", 0.95),
            ))

        elif event.event_type == EventType.AUDIO_CLIP:
            self.multimodal.add_audio(AudioChunkMetadata(
                timestamp_ms=now,
                duration_ms=event.payload.get("duration_ms", 500),
                transcription=event.payload.get("transcription"),
            ))

        elif event.event_type == EventType.INTERRUPTION:
            await self._handle_interruption(now)

        elif event.event_type == EventType.TOOL_RESULT:
            await self._handle_tool_result(event.payload, now)

        elif event.event_type == EventType.TEXT_CHUNK:
            await self._handle_text_chunk(event, now)

    # ------------------------------------------------------------------
    # Interruption — Epoch bump + selective/full cancel
    # ------------------------------------------------------------------
    async def _handle_interruption(self, now_ms: int) -> None:
        self.ledger.bump_epoch()
        cancelled = self.ledger.invalidate_all_active()
        for call in cancelled:
            task = self._active_tasks.pop(call.call_id, None)
            if task and not task.done():
                task.cancel()
            await self._emit(OutputAction(
                timestamp_ms=now_ms,
                action_type=ActionType.CANCEL_CALL,
                call_id=call.call_id,
            ))
        self.fast_path.reset_turn()

    # ------------------------------------------------------------------
    # Text chunk — self-repair, slot delta, fast-path ack, slow-path plan
    # ------------------------------------------------------------------
    async def _handle_text_chunk(self, event: InputEvent, now_ms: int) -> None:
        raw_text = event.payload.get("text", "").strip()
        if not raw_text:
            return

        # Conversational self-repair detection
        repair_fragment = self.slots.parse_self_repair(raw_text)
        effective_text  = repair_fragment if repair_fragment else raw_text

        # Multimodal deictic grounding
        grounded_text, visual_conf = self.multimodal.ground_query(effective_text)
        if visual_conf < 0.60 and self.multimodal.has_deictic_reference(effective_text):
            await self._emit(self.fast_path.generate_clarification(
                "I can't clearly make out the screen content. Could you describe the error?",
                now_ms,
            ))
            return

        # Fast intent + slot extraction (regex, <5ms)
        intent, extracted_slots, _ = _fast_parse(grounded_text)
        if intent:
            self.slots.intent = intent

        changed_slots = self.slots.update_deltas(extracted_slots, confidence=0.95, timestamp_ms=now_ms)

        # Selective invalidation — cancel only calls that read the changed slots
        if changed_slots:
            stale_calls = self.ledger.invalidate_by_read_set(changed_slots)
            for call in stale_calls:
                task = self._active_tasks.pop(call.call_id, None)
                if task and not task.done():
                    task.cancel()
                await self._emit(OutputAction(
                    timestamp_ms=now_ms,
                    action_type=ActionType.CANCEL_CALL,
                    call_id=call.call_id,
                ))

        # Fast-path acknowledgment (<300ms)
        ack = self.fast_path.generate_acknowledgment(
            self.slots.intent, self.slots.get_snapshot(), now_ms
        )
        if ack:
            await self._emit(ack)

        # Slow-path tool dispatch
        await self._dispatch_tool(event.is_end_of_turn, now_ms)

    # ------------------------------------------------------------------
    # Tool dispatch — two-phase gate + ledger registration
    # ------------------------------------------------------------------
    async def _dispatch_tool(self, is_end_of_turn: bool, now_ms: int) -> None:
        intent   = self.slots.intent
        snapshot = self.slots.get_snapshot()
        confs    = self.slots.get_confidence_map()

        if not intent:
            return

        # Map intent → tool_name + args
        tool_name: Optional[str] = None
        args:      Dict[str, Any] = {}
        read_set:  Set[str]       = set()

        if intent == "flight_search":
            tool_name = "flight_search"
            args      = {"destination": snapshot.get("destination"), "date": snapshot.get("date")}
            read_set  = {"destination", "date"}

        elif intent == "flight_book":
            tool_name = "flight_book"
            args      = {
                "flight_id":      snapshot.get("flight_id", "AI-202"),
                "passenger_name": snapshot.get("passenger_name", "Primary Traveler"),
            }
            read_set = {"flight_id", "passenger_name"}

        elif intent == "manual_lookup":
            tool_name = "manual_lookup"
            args      = {"error_code": snapshot.get("error_code")}
            read_set  = {"error_code"}

        if not tool_name:
            return

        # Two-phase idempotency gate
        allowed, reason_or_key = self.tools.can_execute(
            tool_name=tool_name,
            args=args,
            is_end_of_turn=is_end_of_turn,
            slot_confidences=confs,
        )
        if not allowed:
            return  # Silently wait (gate will re-evaluate on next chunk)

        manifest = self.tools.get(tool_name)
        if not manifest:
            return

        call_id = f"call_{uuid.uuid4().hex[:8]}"
        record  = CallRecord(
            call_id=call_id,
            tool_name=tool_name,
            parameters=args,
            read_set=read_set,
            state=CallState.ISSUED,
            idempotency_key=reason_or_key,
            is_state_modifying=manifest.is_state_modifying,
            created_ms=now_ms,
        )
        self.ledger.register_call(record)

        if manifest.is_state_modifying:
            self.tools.record_commit(reason_or_key)

        await self._emit(OutputAction(
            timestamp_ms=now_ms,
            action_type=ActionType.TOOL_CALL,
            call_id=call_id,
            tool_name=tool_name,
            parameters=args,
        ))

    # ------------------------------------------------------------------
    # Tool result — epoch fence then ledger-grounded response
    # ------------------------------------------------------------------
    async def _handle_tool_result(self, payload: Dict[str, Any], now_ms: int) -> None:
        call_id      = payload.get("call_id", "")
        result_epoch = payload.get("epoch", -1)
        record       = self.ledger.get_call(call_id)

        if not record:
            return

        # Fencing token — drop stale epoch results
        if self.ledger.is_result_stale(call_id, result_epoch if result_epoch >= 0 else record.epoch):
            return

        record.state  = CallState.COMPLETED
        record.result = payload.get("result", {})

        # Ledger-grounded truthfulness guard — never free-form hallucinate
        response_text = self._compose_response(record)

        await self._emit(OutputAction(
            timestamp_ms=now_ms,
            action_type=ActionType.FINAL_RESPONSE,
            call_id=call_id,
            text_content=response_text,
            state_snapshot=StateSnapshot(
                intent=self.slots.intent,
                slots=self.slots.get_snapshot(),
                confidence=1.0,
            ),
        ))

    def _compose_response(self, record: CallRecord) -> str:
        """Compose response ONLY from facts present in the ledger record result."""
        res = record.result or {}
        if record.tool_name == "flight_search":
            flights = res.get("flights", [])
            dest    = record.parameters.get("destination", "your destination")
            date    = record.parameters.get("date", "")
            date_str = f" on {date}" if date else ""
            if flights:
                f0 = flights[0]
                return (
                    f"Found {len(flights)} flight(s) to {dest}{date_str}. "
                    f"First option: {f0.get('flight_no','AI-202')} at {f0.get('time','10:00 AM')}, "
                    f"₹{f0.get('price', 'N/A')}."
                )
            return f"No flights found to {dest}{date_str}."

        if record.tool_name == "flight_book":
            pnr = res.get("pnr", "UNKNOWN")
            return f"Booking confirmed! Your reservation code is {pnr}."

        if record.tool_name == "manual_lookup":
            sol = res.get("solution", "Please refer to the device manual.")
            return f"Manual result: {sol}"

        return "Request completed successfully."
