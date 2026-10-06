# Project Progress

## Implementation Phases (SPEC.md v4)

- [x] **Phase 1: DB + Models**
  - SQLite schema creation on startup (`users`, `user_notes`, `workout_plans`, `workout_logs`, `meal_logs`, `daily_logs`, `messages`).
  - Pydantic models for data validation, workout plan structure, and neutral message representations.
  - Complete CRUD helper layer in `src/fitness_coach_agent/db.py`.
  - Workout plan validation and versioning logic.
  - Neutral message format storage with tool calls support.
  - Unit test suite: 9 passing tests in `tests/test_db.py`.

- [ ] **Phase 2: Analysis Engine**
  - Safe AST calculator (`+`, `-`, `*`, `/`, `**`, `round`, `min`, `max`, `sqrt`).
  - `suggest_progression(exercise)` (rule-based evaluation of last 2 sessions).
  - `compare_days(date, exercise?)` (per-exercise 14-day baseline, median volume comparison).
  - Unit tests with mock datasets and edge cases.

- [ ] **Phase 3: LLM Layer**
  - `base.py`: `LLMProvider(ABC)`, `LLMResponse`, `ToolCall`.
  - `openai_provider.py`: OpenAI & OpenRouter via official `openai` SDK.
  - `gemini_provider.py`: Gemini native via `google-genai` SDK.
  - `factory.py`: Provider initialization from `.env`.
  - Provider message conversion unit tests & manual `scripts/smoke_test_llm.py`.

- [ ] **Phase 4: Tools + Agent + CLI**
  - Neutral tool definitions and handlers in `src/fitness_coach_agent/tools.py`.
  - Multi-turn tool execution loop in `src/fitness_coach_agent/agent.py` with Pydantic validation & retry limit.
  - CLI chat loop and command handlers in `src/fitness_coach_agent/cli.py`.

- [ ] **Phase 5: Context Builder**
  - Prompt builder in `src/fitness_coach_agent/context.py`.
  - Dynamic user snapshot, active notes, today's logs.
  - Message windowing (~12 messages, strictly anchored at a user message).

- [ ] **Phase 6: Plan Flow**
  - Generate and save workout plan flows with structured validation.

- [ ] **Phase 7: Chat Logging & Review**
  - Natural language logging for workouts, meals, daily stats.
  - `/logs <days>` CLI view command.

