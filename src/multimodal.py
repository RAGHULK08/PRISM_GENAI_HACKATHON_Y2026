"""multimodal.py
Multimodal ring buffers for video frames and audio clips.
Provides deictic grounding ("this error", "that button") for a 1.5x score multiplier.
"""
import re
from collections import deque
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

# Deictic reference detector — only triggers when referring to visual content
# Exclude generic uses: "make that", "do that", "is that" — require visual noun context
DEICTIC_PATTERN = re.compile(
    r"\b(this\s+(?:error|screen|image|display|code|button|icon|panel)|"
    r"that\s+(?:error|screen|image|display|code|button|icon|panel)|"
    r"shown\s+(?:here|on\s+screen)|"
    r"on\s+(?:my\s+)?screen|"
    r"in\s+the\s+image)\b",
    re.IGNORECASE
)


class FrameMetadata(BaseModel):
    timestamp_ms:      int
    frame_id:          str          = ""
    ocr_text:          Optional[str] = None
    detected_objects:  List[str]    = Field(default_factory=list)
    confidence:        float        = 0.95


class AudioChunkMetadata(BaseModel):
    timestamp_ms:       int
    duration_ms:        int         = 500
    transcription:      Optional[str] = None
    prosody_features:   Dict[str, float] = Field(default_factory=dict)


class MultimodalBuffer:
    """
    Sliding-window temporal buffer for video frames and audio chunks.

    When a user makes a deictic reference (e.g. "What does this error mean?"),
    the latest frame's OCR text is injected into the tool query automatically.
    If visual confidence < 0.70, a clarification is requested instead of guessing.
    """
    def __init__(self, max_frames: int = 10, max_audio: int = 20):
        self._frames: deque[FrameMetadata]       = deque(maxlen=max_frames)
        self._audio:  deque[AudioChunkMetadata]  = deque(maxlen=max_audio)

    def add_frame(self, frame: FrameMetadata) -> None:
        self._frames.append(frame)

    def add_audio(self, audio: AudioChunkMetadata) -> None:
        self._audio.append(audio)

    def has_deictic_reference(self, text: str) -> bool:
        return bool(DEICTIC_PATTERN.search(text))

    def get_latest_frame(self) -> Optional[FrameMetadata]:
        return self._frames[-1] if self._frames else None

    def ground_query(self, query: str) -> Tuple[str, float]:
        """
        Enrich the query with visual context if deictic terms are present.

        Returns:
            (grounded_query, visual_confidence)
            If no deictic reference:   (original_query, 1.0)
            If no frame available:     (original_query, 0.0)
            If low confidence (<0.70): caller should request clarification
        """
        if not self.has_deictic_reference(query):
            return query, 1.0

        latest = self.get_latest_frame()
        if not latest:
            return query, 0.0

        enrichment: List[str] = []
        if latest.ocr_text:
            enrichment.append(f"Visual Text: '{latest.ocr_text}'")
        if latest.detected_objects:
            enrichment.append(f"Objects: {', '.join(latest.detected_objects)}")

        context = " | ".join(enrichment)
        grounded = f"{query} [Grounding: {context}]"
        return grounded, latest.confidence

    def get_recent_audio_context(self, window_ms: int = 5000) -> List[AudioChunkMetadata]:
        """Return audio chunks from the last window_ms milliseconds."""
        if not self._audio:
            return []
        latest_ts = self._audio[-1].timestamp_ms
        return [a for a in self._audio if a.timestamp_ms >= latest_ts - window_ms]
