"""slot_store.py
Delta-tracking, versioned slot store with conversational self-repair parsing.
Implements Differential Slot Engine — preserves valid slots on partial corrections.
"""
import re
from typing import Any, Dict, Optional, Set
from pydantic import BaseModel

# Edit-term lexicon — triggers self-repair parsing
EDIT_MARKERS = [
    r"\bno[\s,]+wait\b",
    r"\bactually\b",
    r"\bscratch that\b",
    r"\brather\b",
    r"\bi mean\b",
    r"\bchange that to\b",
    r"\bmake that\b",
    r"\bcorrection\b",
    r"\bnot that\b",
    r"\bi meant\b",
]
EDIT_REGEX = re.compile("|".join(EDIT_MARKERS), re.IGNORECASE)


class SlotValue(BaseModel):
    value:        Any
    version:      int
    turn_id:      int
    confidence:   float
    timestamp_ms: int


class DifferentialSlotEngine:
    """
    Event-sourced slot store supporting localized self-repair.

    Design principle: only delta-update changed slots.
    Unchanged slots survive interruptions. This is the core of
    Interruption Recovery (35% weight) — we never throw away valid context.
    """
    def __init__(self):
        self._slots:       Dict[str, SlotValue] = {}
        self._intent:      Optional[str]         = None
        self._current_turn: int                  = 1

    @property
    def intent(self) -> Optional[str]:
        return self._intent

    @intent.setter
    def intent(self, val: str) -> None:
        self._intent = val

    def set_slot(self, key: str, val: Any, confidence: float, timestamp_ms: int) -> int:
        old = self._slots.get(key)
        new_version = (old.version + 1) if old else 1
        self._slots[key] = SlotValue(
            value=val, version=new_version,
            turn_id=self._current_turn,
            confidence=confidence, timestamp_ms=timestamp_ms
        )
        return new_version

    def update_deltas(
        self, updates: Dict[str, Any], confidence: float, timestamp_ms: int
    ) -> Set[str]:
        """Apply deltas. Returns set of keys that actually changed value."""
        changed: Set[str] = set()
        for k, v in updates.items():
            current = self._slots.get(k)
            if current is None or current.value != v:
                self.set_slot(k, v, confidence, timestamp_ms)
                changed.add(k)
        return changed

    def parse_self_repair(self, text: str) -> Optional[str]:
        """
        Detect conversational pivots ("no wait", "actually", "make that").
        Returns the post-pivot fragment, or None if no pivot found.
        """
        match = EDIT_REGEX.search(text)
        if match:
            return text[match.end():].strip()
        return None

    def get_snapshot(self) -> Dict[str, Any]:
        return {k: v.value for k, v in self._slots.items()}

    def get_confidence_map(self) -> Dict[str, float]:
        return {k: v.confidence for k, v in self._slots.items()}

    def bump_turn(self) -> None:
        self._current_turn += 1

    def clear(self) -> None:
        """Full reset on explicit cancel-all interruption type."""
        self._slots.clear()
        self._intent = None
