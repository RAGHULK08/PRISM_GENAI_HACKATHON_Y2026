"""fast_path.py
Sub-300ms floor: substantive slot-echoing acknowledgments + adaptive filler scheduler.
No LLM in the critical path. Rules, templates, regex only.
Prevents false completion claims (Quality multiplier guard).
"""
from typing import Dict, List, Optional
from protocol import ActionType, OutputAction, StateSnapshot


# Context-aware filler pools keyed by detected intent
CONTEXT_FILLERS: Dict[str, List[str]] = {
    "flight_search": [
        "Checking available flights for you…",
        "Searching airline schedules…",
        "Looking into flight options…",
    ],
    "flight_book": [
        "Securing that reservation now…",
        "Processing the booking details…",
    ],
    "manual_lookup": [
        "Checking the device manual…",
        "Looking up that error code…",
        "Reviewing diagnostics…",
    ],
    "default": [
        "Checking that right away…",
        "Looking into this now…",
        "On it…",
    ],
}


class FastPathEngine:
    """
    Handles the sub-300ms critical path:
      • Slot-echoing acknowledgments (substantive, truthful, cheap)
      • Contextual progress fillers (capped, non-repetitive, no completion language)
      • Clarification fallback when confidence falls below threshold

    Completion language ("done", "booked", "confirmed") is NEVER emitted here.
    Only the ledger-grounded composer in agent.py may assert completions.
    """
    def __init__(self, max_fillers_per_turn: int = 2):
        self._filler_count:        int = 0
        self._max_fillers_per_turn: int = max_fillers_per_turn
        self._filler_index:        Dict[str, int] = {}

    def reset_turn(self) -> None:
        self._filler_count = 0
        self._filler_index.clear()

    def generate_acknowledgment(
        self,
        intent:       Optional[str],
        slots:        Dict[str, object],
        timestamp_ms: int,
    ) -> Optional[OutputAction]:
        """
        Immediate, truth-grounded acknowledgment.
        Echoes back only slots that are actually populated.
        """
        text: Optional[str] = None

        if intent == "flight_search":
            dest = slots.get("destination")
            date = slots.get("date")
            if dest and date:
                text = f"Searching flights to {dest} on {date}…"
            elif dest:
                text = f"Searching flights to {dest}…"
            elif date:
                text = f"Searching flights on {date}…"
            else:
                text = "Searching available flights…"

        elif intent == "flight_book":
            flight = slots.get("flight_id")
            text = f"Booking flight {flight}…" if flight else "Processing your booking…"

        elif intent == "manual_lookup":
            err = slots.get("error_code")
            text = f"Looking up {err} in the manual…" if err else "Checking device manual…"

        if text is None:
            return None

        return OutputAction(
            timestamp_ms=timestamp_ms,
            action_type=ActionType.SPOKEN_FILLER,
            text_content=text,
            state_snapshot=StateSnapshot(intent=intent, slots=slots),
        )

    def get_progress_filler(
        self,
        intent:       Optional[str],
        timestamp_ms: int,
    ) -> Optional[OutputAction]:
        """
        Emits a capped, varied progress filler during slow-path wait.
        Hard cap: max_fillers_per_turn. Never repeats the same phrase.
        """
        if self._filler_count >= self._max_fillers_per_turn:
            return None

        key  = intent or "default"
        pool = CONTEXT_FILLERS.get(key, CONTEXT_FILLERS["default"])
        idx  = self._filler_index.get(key, 0)
        text = pool[idx % len(pool)]
        self._filler_index[key] = idx + 1
        self._filler_count += 1

        return OutputAction(
            timestamp_ms=timestamp_ms,
            action_type=ActionType.SPOKEN_FILLER,
            text_content=text,
        )

    def generate_clarification(
        self,
        reason:       str,
        timestamp_ms: int,
    ) -> OutputAction:
        """Explicit clarification request when slot confidence is too low."""
        return OutputAction(
            timestamp_ms=timestamp_ms,
            action_type=ActionType.CLARIFICATION,
            text_content=reason,
        )
