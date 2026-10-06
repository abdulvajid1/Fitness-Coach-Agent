# Fitness Coach Agent – MVP Spec (v4)

This file is the source of truth. If something here is unclear or conflicts, ask before guessing. If you change a design decision during implementation, update this file.

## 1. Goal
A CLI chat fitness coach that:
1. Onboards a user (name, height, weight, goal).
2. Stores a weekly workout plan (the user's own, or one generated for their goal).
3. Answers fitness questions using the user's own data.
4. Logs workouts, meals, and a few daily factors from chat.
5. Explains performance dips ("why was I weak today?") and suggests progression ("add weight or reps?") using deterministic Python logic, with the LLM explaining the results.

## 2. Principles
- **Keep it simple.** No auth, no REST API, no conversation summarization, no vector DB, no wrapper frameworks (no LangChain, LiteLLM, etc.); provider SDKs only inside `fitness_coach_agent/llm/`. Add nothing that is not in this spec.
- **The DB is the source of truth.** The LLM never "remembers" user data. It reads and writes through tools.
- **Math and analysis happen in code, not in the LLM.**
- **Never invent user data.** If data is missing, ask the user, save the answer, then continue.
- **Recoverable.** A bad tool call, bad input, or API error must never crash the chat.
- **Single user in the MVP:** the CLI uses `user_id = 1`. Keep `user_id` in every table for later.

## 3. Stack
- Python 3.11+, managed with `uv`
- `sqlite3` (standard library), Pydantic v2
- `openai` and `google-genai` Python SDKs (one per provider, section 4), `python-dotenv`
- `pytest`
- CLI entry: `uv run python -m fitness_coach_agent.cli` (or `uv run fitness-coach-agent`)

## 4. LLM layer (`src/fitness_coach_agent/llm/`)
An abstract provider interface with one implementation per provider, each using that provider's own SDK. The rest of the app only knows the interface and a neutral message format.

### 4.1 Neutral message format (used everywhere in the app and stored in the DB)
```python
{"role": "user" | "assistant" | "tool",
 "content": str | None,
 "tool_calls": [{"id": str, "name": str, "arguments": dict}] | None,   # assistant only
 "tool_call_id": str | None,    # tool results only
 "tool_name": str | None}       # tool results only
```
Tools are also defined once in a neutral form: `{"name", "description", "parameters": <JSON schema>}`. Each provider converts them to its own format.

### 4.2 Interface (`src/fitness_coach_agent/llm/base.py`)
```python
class LLMProvider(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse: ...

class LLMResponse(BaseModel):
    text: str | None
    tool_calls: list[ToolCall]     # ToolCall: id, name, arguments (dict)
```
`chat` receives the system prompt as the first message (`role: "system"`) and each provider maps it to its own mechanism (for example Gemini's system instruction).

### 4.3 Implementations
| File | Class | SDK | Used for |
|---|---|---|---|
| `openai_provider.py` | `OpenAIProvider` | `openai` | OpenAI. Also OpenRouter, via `LLM_BASE_URL` |
| `gemini_provider.py` | `GeminiProvider` | `google-genai` | Gemini (native) |
| `factory.py` | `get_provider()` | | Reads `.env` and returns the right provider |

Adding a provider later means adding one file and one line in the factory. Nothing else changes.

`.env` (commit `.env.example`, never `.env`):
```
LLM_PROVIDER=openai        # openai | openrouter | gemini
LLM_MODEL=
LLM_API_KEY=
LLM_BASE_URL=              # only for openrouter (e.g. https://openrouter.ai/api/v1); check provider docs
```

### 4.4 Rules for every provider
- Convert neutral messages and tools to the provider's format, and convert the response back to `LLMResponse`. Provider-specific objects must never leak outside `fitness_coach_agent/llm/`.
- If a provider does not give tool call ids (Gemini may not), generate them (for example `call_<uuid>`), so the stored history is consistent.
- Tool results are matched back to calls by id (or by tool name where the provider requires it). Handle strict role ordering (assistant tool calls must be immediately followed by their tool results).
- Handle empty or null content alongside tool calls.
- Retry with exponential backoff on rate limits and network errors. Give a clear error message for a bad API key or model name.
- Use only core features: chat, tool calling, system prompt. No streaming, no provider-specific extras in the MVP.
- Keep each provider file small (aim for under ~100 lines).

## 5. Database (`src/fitness_coach_agent/db.py`, SQLite)
Create tables on startup if they do not exist.

```sql
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  name TEXT, height_cm REAL, weight_kg REAL,
  goal TEXT,                      -- fat_loss, muscle_gain, general_fitness
  onboarding_done INTEGER DEFAULT 0
);  -- fields nullable so partial onboarding works

CREATE TABLE user_notes (         -- the only long-term memory
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  category TEXT NOT NULL,         -- injury, equipment, diet, preference, schedule, other
  content TEXT NOT NULL,
  active INTEGER DEFAULT 1
);

CREATE TABLE workout_plans (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  version INTEGER NOT NULL,
  is_active INTEGER DEFAULT 1,
  plan_json TEXT NOT NULL         -- see section 6
);

CREATE TABLE workout_logs (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  date TEXT NOT NULL,             -- YYYY-MM-DD
  exercise TEXT NOT NULL,
  set_number INTEGER, reps INTEGER, weight_kg REAL,
  rpe REAL                        -- optional effort 1-10
);

CREATE TABLE meal_logs (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  date TEXT NOT NULL,
  description TEXT NOT NULL,
  calories REAL, protein_g REAL   -- optional estimates
);

CREATE TABLE daily_logs (         -- one row per day
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  date TEXT NOT NULL,
  sleep_hours REAL, energy INTEGER, notes TEXT,   -- energy 1-10, all optional
  UNIQUE(user_id, date)
);

CREATE TABLE messages (           -- short-term chat history, neutral message format (section 4.1)
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  role TEXT NOT NULL,             -- user / assistant / tool
  content TEXT,
  tool_calls TEXT,                -- JSON list of {id, name, arguments}, assistant messages only
  tool_call_id TEXT,              -- tool result messages only
  tool_name TEXT,                 -- tool result messages only
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```
Workout, meal, and daily logs together describe how a day went.

## 6. Workout plan format (`src/fitness_coach_agent/models.py`)
Stored as JSON in `plan_json`, validated with Pydantic before saving. Updating a plan inserts a new row (`version + 1`) and deactivates the old one. Old versions are kept.

```json
{"days": [{"day": "Monday", "focus": "Push",
  "exercises": [{"name": "Bench Press", "sets": 3, "reps_min": 8, "reps_max": 12, "weight_kg": 40}]}]}
```

## 7. Context building (`src/fitness_coach_agent/context.py`)
The prompt is rebuilt every turn, in this order:
1. **System prompt** (role and rules from section 9).
2. **User snapshot** from the DB: profile, with missing fields listed as `missing: [...]`, the goal, and all active user notes.
3. **Today's plan day** and **today's logs so far** (short text).
4. **Recent messages**: the last ~12 from `messages`. The window must always **start at a `user` message** (extend or shrink slightly if needed), so a `tool` message never appears without its assistant `tool_calls` message.
5. **Current user message.**

Rules:
- **Short-term memory** = recent messages. **Long-term memory** = `user_notes` only. No summarization.
- When the user states a durable fact ("bad left knee", "only dumbbells", "vegetarian"), the agent calls `save_note`.
- Older logs are never put in the prompt. The agent fetches them with `get_logs`.
- If chat content conflicts with the DB, ask the user and fix the DB.

## 8. Tools (`src/fitness_coach_agent/tools.py`)
Every tool returns JSON. When data is absent it returns `{"missing": [...]}`. Arguments are validated with Pydantic. On a validation error, return the error as the tool result so the model can retry (max 2 retries per tool call).

| Tool | Purpose |
|---|---|
| `get_profile()` / `update_profile(fields)` | Read and save profile |
| `get_active_plan()` / `save_plan(plan_json)` | Read and save plan versions |
| `log_workout(date, exercise, sets[])` | Save sets |
| `log_meal(date, description, calories?, protein_g?)` | Save a meal |
| `log_daily(date, sleep_hours?, energy?, notes?)` | Upsert the day |
| `get_logs(type, start_date, end_date)` | Read logs (default last 14 days, max ~50 rows) |
| `save_note(category, content)` / `update_note(id, ...)` | Long-term facts; `update_note` can deactivate a note |
| `calculator(expression)` | General math (BMI, calories, 1RM, etc.) |
| `compare_days(date, exercise?)` | Why was a day weak? |
| `suggest_progression(exercise)` | Weight or reps? |

**Calculator:** parse with Python's `ast` and a strict whitelist. **Never use `eval()`.** Supported: `+ - * / ** ( )`, `round`, `min`, `max`, `sqrt`. Inputs come from the DB, never guessed. If an input is missing, the agent asks the user.

## 9. Agent behavior (system prompt rules)
- If `onboarding_done = 0`, ask only for missing profile fields, one or two at a time. When complete, set `onboarding_done = 1`.
- Then ask: "Do you have a weekly workout plan, or should I create one for your goal?" Save theirs, or generate one, and call `save_plan`.
- Before any task that needs data, check that it exists. If missing, ask, save, and continue.
- When the user reports food, workouts, or sleep, call the log tool and confirm in one short line. Assume today if no date is given.
- Save durable facts with `save_note`.
- On a tool error, say so briefly and retry or ask the user.
- General advice comes from model knowledge, personalized with the user's data. For pain or medical issues, suggest seeing a professional.

## 10. Analysis logic (`src/fitness_coach_agent/analysis.py`, pure Python, no LLM)

**`suggest_progression(exercise)`**: use the last 2 sessions of the exercise.
- All sets at `reps_max` with RPE <= 8 (or no RPE logged): increase weight (+2.5 kg, or +1 to 2 kg for small lifts) and reset to `reps_min`.
- Reps inside the range: keep the weight and add reps.
- Below `reps_min` in both sessions: keep or reduce the weight.
- Not enough sessions: return `{"error": "not_enough_data"}`.
- Return the recommendation plus the numbers behind it. The LLM explains it.

**`compare_days(date, exercise?)`**: explain why a day went worse than usual.
- Compare per exercise, not total session volume (a leg day and an arm day are not comparable). For the target day, take the exercise(s) done that day (or the given exercise).
- Baseline = the same exercise on other days in the previous 14 days. Exclude the target day. "Good days" = baseline sessions with volume (reps x weight) at or above the baseline median.
- Compare the target day against the good days on: exercise volume, sleep_hours, energy, calories, protein, and days since the last session of that exercise.
- Return the differences sorted by size. The LLM turns them into a plain explanation.
- Not enough baseline data: return `{"error": "not_enough_data"}`.

## 11. Agent loop and CLI (`src/fitness_coach_agent/agent.py`, `src/fitness_coach_agent/cli.py`)
- Loop: build context, call the LLM, execute any tool calls, append the results, and call the LLM again until it returns plain text. Set a maximum number of tool iterations per turn (for example 8) so it cannot loop forever.
- Save every message (including tool calls and tool results) to `messages`.
- CLI commands: `/logs <days>` (show recent workouts, meals, daily logs), `/help`, `/exit`.
- No crash on API errors: print a friendly error and keep the session.

## 12. Project structure
```
src/
  fitness_coach_agent/
    cli.py        # chat loop and commands
    agent.py      # tool-calling loop
    llm/
      base.py             # LLMProvider ABC, LLMResponse, ToolCall
      openai_provider.py  # OpenAI + OpenRouter
      gemini_provider.py  # Gemini (google-genai)
      factory.py          # get_provider() from .env
    context.py    # prompt builder (section 7)
    tools.py      # tool schemas and handlers
    db.py         # tables and CRUD
    models.py     # Pydantic models
    analysis.py   # calculator, progression, compare_days
tests/
scripts/
  smoke_test_llm.py   # manual test against real providers
.env.example
.gitignore            # includes .env
pyproject.toml
SPEC.md
PROGRESS.md
```

## 13. Build phases
Work on one phase at a time. **Stop after each phase** so the user can review, run the tests, and commit. Update `PROGRESS.md` at the end of each phase.

1. **DB + models**: tables, CRUD, Pydantic models, plan validation, with tests.
2. **Analysis**: calculator, `suggest_progression`, `compare_days`, with tests on fake data.
3. **LLM layer**: `base.py`, `OpenAIProvider`, `GeminiProvider`, `factory.py`, plus `scripts/smoke_test_llm.py` (the same tool-call round trip on OpenAI, OpenRouter, and Gemini). Build `OpenAIProvider` first and test it; then add `GeminiProvider`.
4. **Tools + agent + CLI**: onboarding and missing-data handling.
5. **Context builder**: prompt assembly, message storage, user notes.
6. **Plan flow**: save the user's plan or generate one.
7. **Chat logging** for workouts, meals, and daily stats, plus the `/logs` command.

## 14. Testing
- Unit tests must not call real APIs: mock `LLMProvider` in pytest (a fake provider returning scripted responses). Real providers are covered only by `scripts/smoke_test_llm.py`, run manually.
- Required tests:
  - DB CRUD, plan validation, plan versioning.
  - Calculator: correct math, and rejection of unsafe input (e.g. `__import__('os')`).
  - `suggest_progression` and `compare_days` on fake data, including the "not enough data" cases and the target day excluded from the baseline.
  - Context: snapshot lists missing fields; recent-messages window starts at a `user` message and never orphans a `tool` message.
  - Providers: neutral to provider message/tool conversion and back, including tool results and missing tool call ids (test conversion functions without network calls).
  - Tools: invalid arguments return an error and the retry limit works.
  - Agent: partial onboarding then resume; "calculate my BMI" with weight missing leads to asking, saving, then calculating; a durable fact becomes a note and shows up in the next session's context.

## 15. Later (not MVP)
REST API for an app (`source` field on logs), log viewer page, Telegram/WhatsApp bot, conversation summarization, weekly summaries, multi-user and auth.