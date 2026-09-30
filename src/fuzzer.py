"""fuzzer.py
Adversarial Timing Fuzzer -- the complete test suite for Theme 05.

Tests the 5 critical boundary conditions:
  Test 1 -- Conversational self-repair  ("Mumbai -> Delhi")
  Test 2 -- Two-phase commit safety      (zero duplicate bookings)
  Test 3 -- Multimodal deictic grounding (1.5x score multiplier)
  Test 4 -- Rapid double interruption    (epoch fence stress test)
  Test 5 -- Stale result fence           (result arrives after cancel)

Run:  python src/fuzzer.py
"""
import asyncio
import sys
import os

# Force UTF-8 output on Windows to avoid cp1252 encode errors
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Ensure src/ is on path when running from project root
sys.path.insert(0, os.path.dirname(__file__))

from clock import VirtualClock
from protocol import ActionType, EventType, InputEvent
from harness import EvaluationHarness

BANNER = """
+======================================================+
|   INTERRUPTIBLE REAL-TIME AGENT -- ADVERSARIAL FUZZER|
|   Theme 05 | Hackathon 2026                          |
+======================================================+
"""

MANIFEST_FLIGHT_SEARCH = {
    "name": "flight_search",
    "description": "Searches available flights by destination and date",
    "parameters": {"required": ["destination", "date"]},
    "is_state_modifying": False,
}
MANIFEST_FLIGHT_BOOK = {
    "name": "flight_book",
    "description": "Creates a confirmed flight reservation",
    "parameters": {"required": ["flight_id", "passenger_name"]},
    "is_state_modifying": True,
}
MANIFEST_MANUAL_LOOKUP = {
    "name": "manual_lookup",
    "description": "Looks up error codes in the device service manual",
    "parameters": {"required": ["error_code"]},
    "is_state_modifying": False,
}


def _ev(ts: int, etype: EventType, payload: dict, session: str = "s1", eot: bool = False) -> tuple:
    return (ts, InputEvent(
        timestamp_ms=ts, event_type=etype,
        session_id=session, payload=payload, is_end_of_turn=eot,
    ))


def _manifest_ev(ts: int, *manifests, session="s1"):
    return _ev(ts, EventType.TOOL_MANIFEST, {"manifests": list(manifests)}, session)


def _text(ts: int, text: str, eot: bool = False, session: str = "s1"):
    return _ev(ts, EventType.TEXT_CHUNK, {"text": text}, session, eot)


def _interrupt(ts: int, session: str = "s1"):
    return _ev(ts, EventType.INTERRUPTION, {}, session)


def _frame(ts: int, ocr: str, conf: float = 0.98, session: str = "s1"):
    return _ev(ts, EventType.VIDEO_FRAME, {
        "ocr_text": ocr,
        "objects": ["display_panel", "warning_indicator"],
        "confidence": conf,
    }, session)


# ---------------------------------------------------------------------------
async def test1_conversational_self_repair() -> float:
    """User says 'to Mumbai' then immediately corrects to 'Delhi'."""
    print("\n" + "="*54)
    print("  TEST 1 -- Conversational Self-Repair (Mumbai -> Delhi)")
    print("="*54)

    h = EvaluationHarness()
    timeline = [
        _manifest_ev(0, MANIFEST_FLIGHT_SEARCH),
        _text(50,  "Find me flights to Mumbai for tomorrow", eot=True),
        _interrupt(200),
        _text(220, "Actually make that Delhi", eot=True),
    ]

    print(f"  [T=  50ms] TEXT_CHUNK  -> 'Find me flights to Mumbai for tomorrow' [EOT]")
    print(f"  [T= 200ms] INTERRUPTION received")
    print(f"  [T= 220ms] TEXT_CHUNK  -> 'Actually make that Delhi' [EOT]")

    result = await h.run_scenario(timeline, is_multimodal=False)

    # Print action trace
    print(f"\n  ACTION TRACE:")
    for entry in h.trace:
        if entry.kind == "ACTION":
            a = entry.action
            label = f"{a.action_type.value:<16}"
            detail = ""
            if a.text_content:  detail = f"'{a.text_content}'"
            if a.call_id:       detail += f" call_id={a.call_id[:14]}"
            if a.tool_name:     detail += f" tool={a.tool_name}"
            tick = "[OK]" if a.action_type != "tool_call" else "?"
            print(f"    [{entry.timestamp:>5}ms] {tick} {label} {detail}")

    result.print_table("Test 1 -- Self-Repair")
    return result.weighted_total


# ---------------------------------------------------------------------------
async def test2_idempotency_safety() -> float:
    """Duplicate booking requests within 50ms must not double-charge."""
    print("\n" + "="*54)
    print("  TEST 2 -- Two-Phase Commit Safety (Zero Duplicates)")
    print("="*54)

    h = EvaluationHarness()
    timeline = [
        _manifest_ev(0, MANIFEST_FLIGHT_BOOK),
        # Partial turn -- must NOT trigger modifying tool
        _text(100, "Book flight AI-202", eot=False),
        # Complete turn -- triggers gate evaluation
        _text(300, "Book flight AI-202 for Primary Traveler", eot=True),
        # Rapid duplicate 50ms later -- must be blocked by idempotency key
        _text(350, "Book flight AI-202 for Primary Traveler", eot=True),
    ]

    print(f"  [T= 100ms] PARTIAL TEXT  -> 'Book flight AI-202' [EOT=False] -> GATED")
    print(f"  [T= 300ms] FULL TEXT     -> 'Book flight AI-202 for Primary Traveler' [EOT=True]")
    print(f"  [T= 350ms] DUPLICATE     -> same text again -> BLOCKED by idempotency key")

    result = await h.run_scenario(timeline, is_multimodal=False)

    book_calls = [t for t in h.trace if t.kind == "ACTION"
                  and t.action.action_type == ActionType.TOOL_CALL
                  and t.action.tool_name == "flight_book"]
    print(f"\n  ACTION TRACE:")
    for entry in h.trace:
        if entry.kind == "ACTION":
            a = entry.action
            tick = "[OK]" if a.action_type != "tool_call" else "?"
            detail = a.text_content or (f"tool={a.tool_name}" if a.tool_name else f"call_id={a.call_id or ''}")
            print(f"    [{entry.timestamp:>5}ms] {tick} {a.action_type.value:<16} {detail}")

    print(f"\n  flight_book calls issued : {len(book_calls)} (expected: 1)")
    dup_status = "[OK] PASS -- Zero duplicates" if len(book_calls) <= 1 else "FAIL FAIL -- Duplicate detected!"
    print(f"  Idempotency gate result  : {dup_status}")

    result.print_table("Test 2 -- Idempotency Safety")
    return result.weighted_total


# ---------------------------------------------------------------------------
async def test3_multimodal_grounding() -> float:
    """Video frame OCR feeds into tool query via deictic reference."""
    print("\n" + "="*54)
    print("  TEST 3 -- Multimodal Grounding (1.5x Multiplier Active)")
    print("="*54)

    h = EvaluationHarness()
    timeline = [
        _manifest_ev(0, MANIFEST_MANUAL_LOOKUP),
        _frame(50, ocr="Error Code: ERR-502 Overheat", conf=0.98),
        _text(120, "What does this error on my screen mean?", eot=True),
    ]

    print(f"  [T=  50ms] VIDEO_FRAME  -> OCR: 'Error Code: ERR-502 Overheat' (conf=0.98)")
    print(f"  [T= 120ms] TEXT_CHUNK   -> 'What does this error on my screen mean?' [EOT]")
    print(f"             +- Deictic 'this' detected -> grounding with latest frame")

    result = await h.run_scenario(timeline, is_multimodal=True)

    print(f"\n  ACTION TRACE:")
    for entry in h.trace:
        if entry.kind == "ACTION":
            a = entry.action
            tick = "[OK]" if a.action_type != "tool_call" else "?"
            detail = a.text_content or (f"tool={a.tool_name} params={a.parameters}" if a.tool_name else "")
            print(f"    [{entry.timestamp:>5}ms] {tick} {a.action_type.value:<16} {detail}")

    result.print_table("Test 3 -- Multimodal Grounding")
    return result.weighted_total


# ---------------------------------------------------------------------------
async def test4_rapid_double_interrupt() -> float:
    """Two interruptions in rapid succession -- epoch must jump twice."""
    print("\n" + "="*54)
    print("  TEST 4 -- Rapid Double Interruption (Epoch Stress Test)")
    print("="*54)

    h = EvaluationHarness()
    timeline = [
        _manifest_ev(0, MANIFEST_FLIGHT_SEARCH),
        _text(50, "Flights to Chennai tomorrow", eot=True),
        _interrupt(100),
        _interrupt(105),   # Second interrupt 5ms later
        _text(200, "Flights to Bangalore on Friday", eot=True),
    ]

    print(f"  [T=  50ms] TEXT_CHUNK  -> 'Flights to Chennai tomorrow'")
    print(f"  [T= 100ms] INTERRUPT   -> epoch 1 -> 2")
    print(f"  [T= 105ms] INTERRUPT   -> epoch 2 -> 3  (rapid double)")
    print(f"  [T= 200ms] TEXT_CHUNK  -> 'Flights to Bangalore on Friday'")

    result = await h.run_scenario(timeline, is_multimodal=False)

    final_epoch = h.agent.ledger.current_epoch
    print(f"\n  Final epoch value        : {final_epoch} (expected: >=2)")
    epoch_status = "[OK] PASS" if final_epoch >= 2 else "FAIL FAIL"
    print(f"  Epoch fence status       : {epoch_status}")

    cancels = [t for t in h.trace if t.kind == "ACTION"
               and t.action.action_type == ActionType.CANCEL_CALL]
    print(f"  Cancel frames emitted    : {len(cancels)}")

    result.print_table("Test 4 -- Double Interruption")
    return result.weighted_total


# ---------------------------------------------------------------------------
async def test5_stale_result_fence() -> float:
    """Result arrives AFTER the call was cancelled -- must be silently dropped."""
    print("\n" + "="*54)
    print("  TEST 5 -- Stale Result Fence (Epoch Drop Verification)")
    print("="*54)

    h = EvaluationHarness()
    timeline = [
        _manifest_ev(0, MANIFEST_FLIGHT_SEARCH),
        _text(50, "Flights to Pune tomorrow", eot=True),
        # Interrupt WHILE the mock tool would be running (tool latency=400ms)
        _interrupt(300),
        # New correct query
        _text(400, "Flights to Hyderabad on Monday", eot=True),
    ]

    print(f"  [T=  50ms] TEXT_CHUNK  -> 'Flights to Pune tomorrow' -> tool issued")
    print(f"  [T= 300ms] INTERRUPT   -> tool for Pune cancelled mid-flight")
    print(f"  [T= 400ms] TEXT_CHUNK  -> 'Flights to Hyderabad on Monday'")
    print(f"             Result for Pune (at T=450ms) must be DROPPED by epoch fence")

    result = await h.run_scenario(timeline, settle_extra_ms=800, is_multimodal=False)

    # The final response, if any, must be about Hyderabad -- not Pune
    finals = [t for t in h.trace if t.kind == "ACTION"
              and t.action.action_type == ActionType.FINAL_RESPONSE]
    print(f"\n  Final responses emitted  : {len(finals)}")
    for f in finals:
        text = f.action.text_content or ""
        dest_ok = "Hyderabad" in text or "hyderabad" in text.lower()
        stale   = "Pune" in text or "pune" in text.lower()
        status  = "[OK] PASS -- Hyderabad result" if dest_ok else ("FAIL STALE -- Pune leaked!" if stale else "WARN?  Neutral")
        print(f"    [{f.timestamp:>5}ms] {status}: '{text[:70]}'")

    result.print_table("Test 5 -- Stale Result Fence")
    return result.weighted_total


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
async def main() -> None:
    print(BANNER)

    scores = {}
    scores["Test 1 -- Self-Repair"]         = await test1_conversational_self_repair()
    scores["Test 2 -- Idempotency Safety"]  = await test2_idempotency_safety()
    scores["Test 3 -- Multimodal Ground"]   = await test3_multimodal_grounding()
    scores["Test 4 -- Double Interrupt"]    = await test4_rapid_double_interrupt()
    scores["Test 5 -- Stale Fence"]         = await test5_stale_result_fence()

    # Aggregate results
    print("\n" + "="*54)
    print("  FINAL AGGREGATE RESULTS")
    print("="*54)
    passed = 0
    for name, score in scores.items():
        cap    = 165.0 if "Multimodal" in name else 105.0
        status = "[OK]" if score >= 80.0 else "FAIL"
        if score >= 80.0:
            passed += 1
        print(f"  {status} {name:<30} {score:>7.2f} / {cap:.0f}")

    print("="*54)
    print(f"  Tests passed: {passed} / {len(scores)}")
    all_ok = passed == len(scores)
    verdict = "ALL TESTS PASSED [OK]" if all_ok else f"{len(scores)-passed} TEST(S) FAILED FAIL"
    print(f"  Verdict     : {verdict}")
    print("="*54)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
