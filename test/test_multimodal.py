"""test_multimodal.py
Unit tests for Multimodal Ring Buffer, Deictic Reference Grounding, and Confidence Estimation.
Part of Theme 05: Interruptible Real-Time Agents test suite.
"""
import os
import sys
import unittest

# Ensure src/ is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from multimodal import AudioChunkMetadata, FrameMetadata, MultimodalBuffer


class TestMultimodal(unittest.TestCase):
    def setUp(self):
        self.buffer = MultimodalBuffer(max_frames=3, max_audio=5)

    def test_frame_and_audio_buffer_sliding_window(self):
        """Verify FIFO buffer discards older frames beyond max_frames."""
        for i in range(5):
            self.buffer.add_frame(FrameMetadata(
                timestamp_ms=100 * i,
                frame_id=f"frame_{i}",
                ocr_text=f"Code {i}",
                confidence=0.9
            ))

        # max_frames is 3 -> only frames 2, 3, 4 should remain
        self.assertEqual(len(self.buffer._frames), 3)
        self.assertEqual(self.buffer.get_latest_frame().frame_id, "frame_4")

    def test_deictic_reference_detection(self):
        """Verify targeted detection of deictic references to visual artifacts."""
        visual_queries = [
            "What does this error on screen mean?",
            "Look at that error code",
            "What is shown on screen right now?",
            "Can you explain the warning in the image?",
        ]
        non_visual_queries = [
            "Book flights to Delhi tomorrow",
            "Actually make that Friday",
            "Can you search for hotels?",
        ]

        for q in visual_queries:
            self.assertTrue(self.buffer.has_deictic_reference(q), f"Should detect deictic in '{q}'")

        for q in non_visual_queries:
            self.assertFalse(self.buffer.has_deictic_reference(q), f"Should NOT detect deictic in '{q}'")

    def test_multimodal_grounding_enrichment(self):
        """Verify query is enriched with latest frame OCR and objects when deictic terms exist."""
        frame = FrameMetadata(
            timestamp_ms=500,
            frame_id="frame_err",
            ocr_text="ERR-909 Critical Voltage Drop",
            detected_objects=["power_supply", "warning_led"],
            confidence=0.97
        )
        self.buffer.add_frame(frame)

        query = "What does this error on my screen mean?"
        grounded, conf = self.buffer.ground_query(query)

        self.assertIn("ERR-909 Critical Voltage Drop", grounded)
        self.assertIn("power_supply", grounded)
        self.assertEqual(conf, 0.97)

    def test_grounding_without_frame_returns_zero_confidence(self):
        """If user refers to 'this error' but no frames are in buffer, confidence must be 0."""
        empty_buffer = MultimodalBuffer()
        query = "What does this error on my screen mean?"
        grounded, conf = empty_buffer.ground_query(query)

        self.assertEqual(conf, 0.0)
        self.assertEqual(grounded, query)


if __name__ == "__main__":
    unittest.main()
