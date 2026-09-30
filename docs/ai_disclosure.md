
---

### 📄 AI Disclosure

```markdown
# AI Disclosure Statement

## Project: Interruptible Real-Time Voice Agent

### Use of AI Tools in Development

This project was developed with assistance from AI tools in the following capacities:

#### Architecture Design
- **Tool Used**: Google Antigravity (powered by Claude Sonnet / Gemini)
- **Scope**: High-level architectural pattern suggestions including epoch-fencing
  strategy, read-set selective invalidation concept, and two-phase idempotency
  barrier design were explored through AI-assisted brainstorming sessions.
- **Human Contribution**: All final architectural decisions, trade-off evaluations,
  component decomposition, and system integration were made by the developer.

#### Code Generation Assistance
- **Tool Used**: Google Antigravity IDE assistant
- **Scope**: AI assistance was used to generate initial boilerplate for:
  - Pydantic model definitions (`protocol.py`)
  - Async queue scaffolding patterns (`agent.py`)
  - Regex patterns for slot extraction (`fast_path.py`)
- **Human Contribution**: All logic, algorithm implementation, integration,
  bug-fixing, and test scenario design were performed by the developer.
  Every generated snippet was reviewed, modified, and validated manually.

#### Documentation
- **Tool Used**: Google Antigravity
- **Scope**: README structure and AI Disclosure template drafting.
- **Human Contribution**: All technical content, architecture descriptions,
  and submission-specific customization were written by the developer.

### What Was NOT AI-Generated
- Core algorithmic design (epoch fencing, read-set tracking, differential slot engine)
- Integration logic between all 10 modules
- Test case scenario design and adversarial fuzzer logic
- Performance optimization decisions
- All final submitted code (reviewed and validated line-by-line)

### Compliance Statement
This project complies with the hackathon's AI usage policy. All AI-assisted
components are disclosed above. The submitted solution represents the developer's
original intellectual work with AI used strictly as a productivity and exploration tool.

---
*Disclosure prepared in accordance with hackathon submission requirements.*
*Date: September 30, 2026*
