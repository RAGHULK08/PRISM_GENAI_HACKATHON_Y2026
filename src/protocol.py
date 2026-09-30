"""protocol.py
Strict Pydantic v2 data models for all input events and output actions.
Every outgoing payload passes through this schema — Protocol Gate = 10% score weight.
"""
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class EventType(str, Enum):
    TEXT_CHUNK   = "text_chunk"
    AUDIO_CLIP   = "audio_clip"
    VIDEO_FRAME  = "video_frame"
    INTERRUPTION = "interruption"
    TOOL_RESULT  = "tool_result"
    TOOL_MANIFEST = "tool_manifest"


class InputEvent(BaseModel):
    timestamp_ms:   int
    event_type:     EventType
    session_id:     str
    payload:        Dict[str, Any] = Field(default_factory=dict)
    is_end_of_turn: bool = False


class ActionType(str, Enum):
    SPOKEN_FILLER  = "spoken_filler"
    TOOL_CALL      = "tool_call"
    CANCEL_CALL    = "cancel_call"
    CLARIFICATION  = "clarification"
    FINAL_RESPONSE = "final_response"


class StateSnapshot(BaseModel):
    intent:     Optional[str]       = None
    slots:      Dict[str, Any]      = Field(default_factory=dict)
    confidence: float               = 1.0
    turn_id:    int                 = 0


class OutputAction(BaseModel):
    timestamp_ms:    int
    action_type:     ActionType
    call_id:         Optional[str]            = None
    tool_name:       Optional[str]            = None
    parameters:      Optional[Dict[str, Any]] = None
    text_content:    Optional[str]            = None
    state_snapshot:  Optional[StateSnapshot]  = None

    @model_validator(mode="after")
    def validate_tool_call_fields(self) -> "OutputAction":
        if self.action_type == ActionType.TOOL_CALL:
            if not self.tool_name:
                raise ValueError("TOOL_CALL action requires tool_name")
            if not self.call_id:
                raise ValueError("TOOL_CALL action requires call_id")
        if self.action_type == ActionType.CANCEL_CALL:
            if not self.call_id:
                raise ValueError("CANCEL_CALL action requires call_id")
        return self
