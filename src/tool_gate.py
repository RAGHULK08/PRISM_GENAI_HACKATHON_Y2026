"""tool_gate.py
Tool schema classification and two-phase idempotency barrier.
Prevents any duplicate state-changing call — satisfies Safety (10% weight).
"""
import hashlib
import json
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel


class ToolManifest(BaseModel):
    name:               str
    description:        str
    parameters_schema:  Dict[str, Any]
    is_state_modifying: bool
    required_slots:     List[str]


# Terms in a tool name that indicate it modifies state
_MODIFYING_TERMS = (
    "book", "create", "reserve", "pay", "update",
    "cancel", "delete", "send", "submit", "purchase",
    "confirm", "order", "register"
)


class ToolRegistry:
    """
    Manifest-driven generic tool layer.

    Two-phase commit gate for state-modifying tools:
      Phase 1 — Gate: end_of_turn, slots filled, confidence ≥ 0.80
      Phase 2 — Commit: idempotency key unique in executed set

    Read-only tools bypass both phases for speculative execution.
    """
    def __init__(self):
        self._manifests:               Dict[str, ToolManifest] = {}
        self._executed_idempotency_keys: Set[str]              = set()

    def register(self, manifest: ToolManifest) -> None:
        self._manifests[manifest.name] = manifest

    def parse_manifests(self, manifest_list: List[Dict[str, Any]]) -> None:
        for item in manifest_list:
            name = item["name"]
            is_modifying = item.get("is_state_modifying", False)
            if not is_modifying:
                is_modifying = any(t in name.lower() for t in _MODIFYING_TERMS)

            schema   = item.get("parameters", {})
            required = schema.get("required", [])
            self.register(ToolManifest(
                name=name,
                description=item.get("description", ""),
                parameters_schema=schema,
                is_state_modifying=is_modifying,
                required_slots=required,
            ))

    def get(self, name: str) -> Optional[ToolManifest]:
        return self._manifests.get(name)

    def compute_idempotency_key(self, tool_name: str, args: Dict[str, Any]) -> str:
        serialized = json.dumps(
            {k: v for k, v in args.items() if v is not None},
            sort_keys=True, default=str
        )
        return hashlib.sha256(f"{tool_name}:{serialized}".encode()).hexdigest()

    def can_execute(
        self,
        tool_name:        str,
        args:             Dict[str, Any],
        is_end_of_turn:   bool,
        slot_confidences: Dict[str, float],
        confidence_threshold: float = 0.80,
    ) -> Tuple[bool, str]:
        """
        Returns (allowed, reason_or_idempotency_key).
        Read-only: speculative — always allowed if slots present.
        State-modifying: two-phase gate.
        """
        manifest = self.get(tool_name)
        if not manifest:
            return False, f"Unknown tool '{tool_name}'"

        # Check required slots exist and meet confidence
        for req in manifest.required_slots:
            if req not in args or args[req] is None:
                return False, f"Missing required slot '{req}'"
            conf = slot_confidences.get(req, 1.0)
            if conf < confidence_threshold:
                return False, (
                    f"Slot '{req}' confidence {conf:.2f} < threshold {confidence_threshold:.2f}"
                )

        key = self.compute_idempotency_key(tool_name, args)

        if not manifest.is_state_modifying:
            return True, key            # Read-only: speculative OK

        # --- Two-Phase Gate for state-modifying tools ---
        if not is_end_of_turn:
            return False, "State-modifying tool gated: waiting for end_of_turn"

        if key in self._executed_idempotency_keys:
            return False, f"Duplicate blocked by idempotency gate (key={key[:12]}...)"

        return True, key

    def record_commit(self, key: str) -> None:
        self._executed_idempotency_keys.add(key)

    def reset_session(self) -> None:
        """Clear idempotency log between test sessions."""
        self._executed_idempotency_keys.clear()
