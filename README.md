# Interruptible Real-Time Voice Agent
> **Theme 05**: Interruptible Real-Time Agents — Fast-and-Slow Execution and Robust Interruption Handling.

## Overview
A voice-native assistant architecture operating in full-duplex mode. It addresses concurrency and state-consistency challenges when users interrupt, self-correct mid-sentence, or pivot topics.

### Key Architectural Inventions
1. **Epoch-Fenced Call Ledger**: State machine (`PLANNED -> ISSUED -> RUNNING -> COMPLETED | CANCELLED`). Epoch tokens automatically drop late-arriving stale results.
2. **Read-Set Selective Invalidation**: Tracks consumed slot keys for every in-flight call. Localized slot corrections only cancel intersecting calls while unaffected tasks survive.
3. **Two-Phase Idempotency Barrier**: SHA-256 canonical argument hashing ensures zero duplicate executions for state-modifying actions.
4. **Differential Slot Engine**: Event-sourced versioned slots with regex self-repair parser recognizing pivots ("no wait", "actually", "scratch that").
5. **Multimodal Grounding Pipeline**: Ring buffers for frames and audio; grounds deictic references ("this error on screen") with OCR features, triggering clarification when visual confidence is low.
6. **Sub-300ms Fast Path**: Slot-echoing truthful acknowledgments and context-aware progress fillers. Completion claims are ledger-grounded only.

---

## Directory Structure
```
interruptible-realtime-agent/
|-- src/
|   |-- clock.py         # Injectable virtual clock
|   |-- protocol.py      # Pydantic v2 schemas for events and actions
|   |-- slot_store.py    # Differential slot engine & self-repair parser
|   |-- ledger.py        # Call ledger & read-set invalidation
|   |-- tool_gate.py     # Manifest parser & 2-phase idempotency barrier
|   |-- multimodal.py    # Temporal frame & audio buffers + deictic grounding
|   |-- fast_path.py     # Sub-300ms acknowledgments & filler scheduler
|   |-- agent.py         # Unified async coordinator
|   |-- harness.py       # Virtual clock test harness & rubric scorer
|   `-- fuzzer.py        # Adversarial timing fuzzer (5 core scenarios)
|-- tests/
|   |-- test_cancellation.py
|   |-- test_idempotency.py
|   |-- test_slot_repair.py
|   `-- test_multimodal.py
|-- docs/
|   |-- ai_disclosure.md
|   `-- architecture.md
`-- requirements.txt
```

---

## Running Tests

### 1. Adversarial Fuzzer (5 Scenarios)
```bash
python src/fuzzer.py
```

### 2. Unit Test Suite (16 Tests)
```bash
python -m unittest discover -s tests -p "test_*.py" -v
```
