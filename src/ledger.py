"""ledger.py
Call Ledger state machine with Epoch-fenced invalidation and Read-Set tracking.
Central truth store for all in-flight and completed tool calls.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field


class CallState(str, Enum):
    PLANNED    = "PLANNED"
    ISSUED     = "ISSUED"
    RUNNING    = "RUNNING"
    COMPLETED  = "COMPLETED"
    CANCELLED  = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"
    FAILED     = "FAILED"


class CallRecord(BaseModel):
    call_id:            str
    tool_name:          str
    parameters:         Dict[str, Any]  = Field(default_factory=dict)
    read_set:           Set[str]        = Field(default_factory=set)
    state:              CallState       = CallState.PLANNED
    epoch:              int             = 0
    idempotency_key:    str             = ""
    is_state_modifying: bool            = False
    result:             Optional[dict]  = None
    created_ms:         int             = 0

    model_config = {"arbitrary_types_allowed": True}


class CallLedger:
    """
    Central coordinator for calls, epochs, and cancellation.

    Epoch fencing guarantees that results from superseded plan versions
    are silently dropped — the core fix for stale-result race conditions.

    Read-set selective invalidation cancels ONLY tasks whose slot
    dependencies overlap with what the user just corrected.
    """
    def __init__(self):
        self._calls:         Dict[str, CallRecord] = {}
        self.current_epoch:  int                   = 0

    def bump_epoch(self) -> int:
        """Called on interruption or major context shift. Invalidates all old results."""
        self.current_epoch += 1
        return self.current_epoch

    def register_call(self, record: CallRecord) -> None:
        record.epoch = self.current_epoch
        self._calls[record.call_id] = record

    def get_call(self, call_id: str) -> Optional[CallRecord]:
        return self._calls.get(call_id)

    def mark_state(self, call_id: str, new_state: CallState) -> None:
        if call_id in self._calls:
            self._calls[call_id].state = new_state

    def invalidate_by_read_set(self, changed_slots: Set[str]) -> List[CallRecord]:
        """
        Selective invalidation — cancel ONLY calls whose read_set
        intersects with the set of slots that just changed value.
        Calls on unaffected slots survive untouched.
        """
        to_cancel: List[CallRecord] = []
        for call in self._calls.values():
            if call.state in (CallState.PLANNED, CallState.ISSUED, CallState.RUNNING):
                if call.read_set & changed_slots:
                    call.state = CallState.CANCELLED
                    to_cancel.append(call)
        return to_cancel

    def invalidate_all_active(self) -> List[CallRecord]:
        """Full cancellation — used on cancel-all interruption type."""
        to_cancel: List[CallRecord] = []
        for call in self._calls.values():
            if call.state in (CallState.PLANNED, CallState.ISSUED, CallState.RUNNING):
                call.state = CallState.CANCELLED
                to_cancel.append(call)
        return to_cancel

    def get_active_calls(self) -> List[CallRecord]:
        return [
            c for c in self._calls.values()
            if c.state in (CallState.ISSUED, CallState.RUNNING)
        ]

    def is_result_stale(self, call_id: str, result_epoch: int) -> bool:
        """Returns True if the result epoch is older than the record epoch — discard it."""
        rec = self._calls.get(call_id)
        if rec is None:
            return True
        if rec.state == CallState.CANCELLED:
            return True
        # Stale if the result comes from an older epoch than when the call was registered
        if result_epoch < rec.epoch:
            return True
        return False

    def has_active_state_modifying(self) -> bool:
        return any(
            c.is_state_modifying and c.state in (CallState.ISSUED, CallState.RUNNING)
            for c in self._calls.values()
        )

    def summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for call in self._calls.values():
            counts[call.state] = counts.get(call.state, 0) + 1
        return counts
