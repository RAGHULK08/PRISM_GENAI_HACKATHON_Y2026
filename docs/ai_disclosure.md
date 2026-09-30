# AI Disclosure Statement

## Project: Interruptible Real-Time Voice Agent
**Theme**: Theme 05 — Interruptible Real-Time Agents

### Use of AI Tools in Development

This project was developed with assistance from AI coding tools in the following capacities:

#### Architecture Design
- **Tool Used**: Google Antigravity (powered by advanced LLM reasoning engines)
- **Scope**: Brainstorming architectural patterns for full-duplex conversational agents, including epoch-fenced call ledgers, read-set selective invalidation, and two-phase idempotency gates.
- **Human Contribution**: System specifications, rubric alignment, concurrency semantics, and state machine transitions.

#### Code Implementation & Testing
- **Tool Used**: Google Antigravity Agent
- **Scope**: Generating initial scaffolding for Pydantic models (`protocol.py`), fast-path regex parsing, and virtual clock harness orchestration.
- **Human Contribution**: Manual code review, debugging race conditions, implementing boundary tests in `fuzzer.py`, and authoring unit tests in `tests/`.

### Compliance
This project strictly complies with the hackathon's AI usage and disclosure policy. All core algorithms, state stores, and evaluation harnesses were validated and benchmarked locally.
