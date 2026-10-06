"""SQLite database initialization and CRUD operations."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fitness_coach_agent.models import (
    DailyLogRecord,
    MealLogRecord,
    MessageRecord,
    ToolCall,
    UserNote,
    UserProfile,
    WorkoutLogRecord,
    WorkoutPlanRecord,
    WorkoutPlanSchema,
    WorkoutSet,
)

DEFAULT_DB_PATH = "fitness_coach.db"


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create and return a configured sqlite3 connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Create all required tables and indices if they do not exist."""
    schema_sql = """
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY,
      name TEXT,
      height_cm REAL,
      weight_kg REAL,
      goal TEXT,
      onboarding_done INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS user_notes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      category TEXT NOT NULL,
      content TEXT NOT NULL,
      active INTEGER DEFAULT 1,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS workout_plans (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      version INTEGER NOT NULL,
      is_active INTEGER DEFAULT 1,
      plan_json TEXT NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS workout_logs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      date TEXT NOT NULL,
      exercise TEXT NOT NULL,
      set_number INTEGER,
      reps INTEGER,
      weight_kg REAL,
      rpe REAL,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS meal_logs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      date TEXT NOT NULL,
      description TEXT NOT NULL,
      calories REAL,
      protein_g REAL,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS daily_logs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      date TEXT NOT NULL,
      sleep_hours REAL,
      energy INTEGER,
      notes TEXT,
      UNIQUE(user_id, date),
      FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      role TEXT NOT NULL,
      content TEXT,
      tool_calls TEXT,
      tool_call_id TEXT,
      tool_name TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE INDEX IF NOT EXISTS idx_workout_logs_user_date ON workout_logs(user_id, date);
    CREATE INDEX IF NOT EXISTS idx_meal_logs_user_date ON meal_logs(user_id, date);
    CREATE INDEX IF NOT EXISTS idx_daily_logs_user_date ON daily_logs(user_id, date);
    CREATE INDEX IF NOT EXISTS idx_user_notes_user_active ON user_notes(user_id, active);
    CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, id);
    """
    with get_connection(db_path) as conn:
        conn.executescript(schema_sql)


# --- User & Profile CRUD ---


def get_user(user_id: int = 1, db_path: str = DEFAULT_DB_PATH) -> UserProfile | None:
    """Retrieve user by ID."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT id, name, height_cm, weight_kg, goal, onboarding_done FROM users WHERE id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return UserProfile(
            id=row["id"],
            name=row["name"],
            height_cm=row["height_cm"],
            weight_kg=row["weight_kg"],
            goal=row["goal"],
            onboarding_done=bool(row["onboarding_done"]),
        )


def get_or_create_user(user_id: int = 1, db_path: str = DEFAULT_DB_PATH) -> UserProfile:
    """Get existing user or create a new empty profile."""
    user = get_user(user_id, db_path=db_path)
    if user:
        return user
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO users (id, onboarding_done) VALUES (?, 0)",
            (user_id,),
        )
    return UserProfile(id=user_id, onboarding_done=False)


def update_user_profile(user_id: int = 1, db_path: str = DEFAULT_DB_PATH, **fields: Any) -> UserProfile:
    """Update profile fields for the given user."""
    get_or_create_user(user_id, db_path=db_path)

    allowed = {"name", "height_cm", "weight_kg", "goal", "onboarding_done"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}

    if "onboarding_done" in updates:
        updates["onboarding_done"] = 1 if updates["onboarding_done"] else 0

    if updates:
        set_clause = ", ".join(f"{col} = ?" for col in updates.keys())
        params = list(updates.values()) + [user_id]
        with get_connection(db_path) as conn:
            conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", params)

    updated = get_user(user_id, db_path=db_path)
    if not updated:
        raise RuntimeError(f"User {user_id} not found after update")
    return updated


# --- User Notes CRUD ---


def save_note(user_id: int, category: str, content: str, db_path: str = DEFAULT_DB_PATH) -> UserNote:
    """Save a durable fact/note."""
    get_or_create_user(user_id, db_path=db_path)
    note = UserNote(user_id=user_id, category=category, content=content, active=True)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO user_notes (user_id, category, content, active) VALUES (?, ?, ?, 1)",
            (user_id, note.category, note.content),
        )
        note.id = cursor.lastrowid
    return note


def get_active_notes(user_id: int = 1, db_path: str = DEFAULT_DB_PATH) -> list[UserNote]:
    """Retrieve all active notes for a user."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT id, user_id, category, content, active FROM user_notes WHERE user_id = ? AND active = 1 ORDER BY id ASC",
            (user_id,),
        )
        rows = cursor.fetchall()
        return [
            UserNote(
                id=r["id"],
                user_id=r["user_id"],
                category=r["category"],
                content=r["content"],
                active=bool(r["active"]),
            )
            for r in rows
        ]


def update_note(
    note_id: int,
    user_id: int = 1,
    content: str | None = None,
    category: str | None = None,
    active: bool | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> UserNote | None:
    """Update or deactivate a note."""
    updates: dict[str, Any] = {}
    if content is not None:
        updates["content"] = content
    if category is not None:
        dummy = UserNote(user_id=user_id, category=category, content="")
        updates["category"] = dummy.category
    if active is not None:
        updates["active"] = 1 if active else 0

    if updates:
        set_clause = ", ".join(f"{col} = ?" for col in updates.keys())
        params = list(updates.values()) + [note_id, user_id]
        with get_connection(db_path) as conn:
            conn.execute(f"UPDATE user_notes SET {set_clause} WHERE id = ? AND user_id = ?", params)

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT id, user_id, category, content, active FROM user_notes WHERE id = ? AND user_id = ?",
            (note_id, user_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return UserNote(
            id=row["id"],
            user_id=row["user_id"],
            category=row["category"],
            content=row["content"],
            active=bool(row["active"]),
        )


# --- Workout Plans CRUD ---


def save_plan(
    user_id: int,
    plan: WorkoutPlanSchema | dict[str, Any] | str,
    db_path: str = DEFAULT_DB_PATH,
) -> WorkoutPlanRecord:
    """Save a workout plan, incrementing version and deactivating previous active plans."""
    get_or_create_user(user_id, db_path=db_path)

    if isinstance(plan, str):
        validated_plan = WorkoutPlanSchema.model_validate(json.loads(plan))
    elif isinstance(plan, dict):
        validated_plan = WorkoutPlanSchema.model_validate(plan)
    else:
        validated_plan = plan

    plan_json_str = validated_plan.model_dump_json()

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT MAX(version) as max_v FROM workout_plans WHERE user_id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        next_version = (row["max_v"] or 0) + 1

        # Deactivate previous active plans
        conn.execute(
            "UPDATE workout_plans SET is_active = 0 WHERE user_id = ? AND is_active = 1",
            (user_id,),
        )

        cursor = conn.execute(
            "INSERT INTO workout_plans (user_id, version, is_active, plan_json) VALUES (?, ?, 1, ?)",
            (user_id, next_version, plan_json_str),
        )
        record_id = cursor.lastrowid

    return WorkoutPlanRecord(
        id=record_id,
        user_id=user_id,
        version=next_version,
        is_active=True,
        plan_json=plan_json_str,
        plan=validated_plan,
    )


def get_active_plan(user_id: int = 1, db_path: str = DEFAULT_DB_PATH) -> WorkoutPlanRecord | None:
    """Get the currently active plan for a user."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT id, user_id, version, is_active, plan_json FROM workout_plans WHERE user_id = ? AND is_active = 1 ORDER BY version DESC LIMIT 1",
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return WorkoutPlanRecord(
            id=row["id"],
            user_id=row["user_id"],
            version=row["version"],
            is_active=bool(row["is_active"]),
            plan_json=row["plan_json"],
        )


def get_plan_history(user_id: int = 1, db_path: str = DEFAULT_DB_PATH) -> list[WorkoutPlanRecord]:
    """Retrieve full version history of workout plans."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT id, user_id, version, is_active, plan_json FROM workout_plans WHERE user_id = ? ORDER BY version ASC",
            (user_id,),
        )
        rows = cursor.fetchall()
        return [
            WorkoutPlanRecord(
                id=r["id"],
                user_id=r["user_id"],
                version=r["version"],
                is_active=bool(r["is_active"]),
                plan_json=r["plan_json"],
            )
            for r in rows
        ]


# --- Workout Logs CRUD ---


def log_workout(
    user_id: int,
    date: str,
    exercise: str,
    sets: list[WorkoutSet | dict[str, Any]],
    db_path: str = DEFAULT_DB_PATH,
) -> list[WorkoutLogRecord]:
    """Log workout sets for an exercise on a given date."""
    get_or_create_user(user_id, db_path=db_path)
    records: list[WorkoutLogRecord] = []

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT COUNT(*) as cnt FROM workout_logs WHERE user_id = ? AND date = ? AND exercise = ?",
            (user_id, date, exercise),
        )
        row = cursor.fetchone()
        start_set_num = (row["cnt"] or 0) + 1

        for i, s in enumerate(sets):
            set_obj = s if isinstance(s, WorkoutSet) else WorkoutSet.model_validate(s)
            set_num = set_obj.set_number or (start_set_num + i)
            ins_cursor = conn.execute(
                """
                INSERT INTO workout_logs (user_id, date, exercise, set_number, reps, weight_kg, rpe)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, date, exercise, set_num, set_obj.reps, set_obj.weight_kg, set_obj.rpe),
            )
            records.append(
                WorkoutLogRecord(
                    id=ins_cursor.lastrowid,
                    user_id=user_id,
                    date=date,
                    exercise=exercise,
                    set_number=set_num,
                    reps=set_obj.reps,
                    weight_kg=set_obj.weight_kg,
                    rpe=set_obj.rpe,
                )
            )

    return records


def get_workout_logs(
    user_id: int = 1,
    start_date: str | None = None,
    end_date: str | None = None,
    exercise: str | None = None,
    limit: int = 50,
    db_path: str = DEFAULT_DB_PATH,
) -> list[WorkoutLogRecord]:
    """Retrieve workout logs filtered by date range and optional exercise."""
    query = "SELECT id, user_id, date, exercise, set_number, reps, weight_kg, rpe FROM workout_logs WHERE user_id = ?"
    params: list[Any] = [user_id]

    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    if exercise:
        query += " AND LOWER(exercise) = LOWER(?)"
        params.append(exercise)

    query += " ORDER BY date DESC, id DESC LIMIT ?"
    params.append(limit)

    with get_connection(db_path) as conn:
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        return [
            WorkoutLogRecord(
                id=r["id"],
                user_id=r["user_id"],
                date=r["date"],
                exercise=r["exercise"],
                set_number=r["set_number"],
                reps=r["reps"],
                weight_kg=r["weight_kg"],
                rpe=r["rpe"],
            )
            for r in rows
        ]


# --- Meal Logs CRUD ---


def log_meal(
    user_id: int,
    date: str,
    description: str,
    calories: float | None = None,
    protein_g: float | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> MealLogRecord:
    """Log a meal entry."""
    get_or_create_user(user_id, db_path=db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO meal_logs (user_id, date, description, calories, protein_g) VALUES (?, ?, ?, ?, ?)",
            (user_id, date, description, calories, protein_g),
        )
        record_id = cursor.lastrowid
    return MealLogRecord(
        id=record_id,
        user_id=user_id,
        date=date,
        description=description,
        calories=calories,
        protein_g=protein_g,
    )


def get_meal_logs(
    user_id: int = 1,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    db_path: str = DEFAULT_DB_PATH,
) -> list[MealLogRecord]:
    """Retrieve meal logs filtered by date range."""
    query = "SELECT id, user_id, date, description, calories, protein_g FROM meal_logs WHERE user_id = ?"
    params: list[Any] = [user_id]

    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)

    query += " ORDER BY date DESC, id DESC LIMIT ?"
    params.append(limit)

    with get_connection(db_path) as conn:
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        return [
            MealLogRecord(
                id=r["id"],
                user_id=r["user_id"],
                date=r["date"],
                description=r["description"],
                calories=r["calories"],
                protein_g=r["protein_g"],
            )
            for r in rows
        ]


# --- Daily Logs CRUD ---


def log_daily(
    user_id: int,
    date: str,
    sleep_hours: float | None = None,
    energy: int | None = None,
    notes: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> DailyLogRecord:
    """Upsert daily wellness log (sleep, energy, notes)."""
    get_or_create_user(user_id, db_path=db_path)
    DailyLogRecord(user_id=user_id, date=date, sleep_hours=sleep_hours, energy=energy, notes=notes)

    upsert_sql = """
    INSERT INTO daily_logs (user_id, date, sleep_hours, energy, notes)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(user_id, date) DO UPDATE SET
      sleep_hours = COALESCE(excluded.sleep_hours, daily_logs.sleep_hours),
      energy = COALESCE(excluded.energy, daily_logs.energy),
      notes = COALESCE(excluded.notes, daily_logs.notes);
    """
    with get_connection(db_path) as conn:
        conn.execute(upsert_sql, (user_id, date, sleep_hours, energy, notes))

    res = get_daily_log(user_id, date, db_path=db_path)
    if not res:
        raise RuntimeError("Failed to fetch daily log after upsert")
    return res


def get_daily_log(user_id: int, date: str, db_path: str = DEFAULT_DB_PATH) -> DailyLogRecord | None:
    """Retrieve daily log for a specific date."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT id, user_id, date, sleep_hours, energy, notes FROM daily_logs WHERE user_id = ? AND date = ?",
            (user_id, date),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return DailyLogRecord(
            id=row["id"],
            user_id=row["user_id"],
            date=row["date"],
            sleep_hours=row["sleep_hours"],
            energy=row["energy"],
            notes=row["notes"],
        )


def get_daily_logs(
    user_id: int = 1,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    db_path: str = DEFAULT_DB_PATH,
) -> list[DailyLogRecord]:
    """Retrieve daily logs filtered by date range."""
    query = "SELECT id, user_id, date, sleep_hours, energy, notes FROM daily_logs WHERE user_id = ?"
    params: list[Any] = [user_id]

    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)

    query += " ORDER BY date DESC, id DESC LIMIT ?"
    params.append(limit)

    with get_connection(db_path) as conn:
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        return [
            DailyLogRecord(
                id=r["id"],
                user_id=r["user_id"],
                date=r["date"],
                sleep_hours=r["sleep_hours"],
                energy=r["energy"],
                notes=r["notes"],
            )
            for r in rows
        ]


# --- Messages CRUD ---


def save_message(
    user_id: int,
    role: str,
    content: str | None = None,
    tool_calls: list[dict[str, Any] | ToolCall] | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> MessageRecord:
    """Store a message in neutral format."""
    get_or_create_user(user_id, db_path=db_path)

    tool_calls_json = None
    tc_models: list[ToolCall] | None = None
    if tool_calls is not None:
        tc_models = [
            tc if isinstance(tc, ToolCall) else ToolCall.model_validate(tc)
            for tc in tool_calls
        ]
        tool_calls_json = json.dumps([tc.model_dump() for tc in tc_models])

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO messages (user_id, role, content, tool_calls, tool_call_id, tool_name)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, role, content, tool_calls_json, tool_call_id, tool_name),
        )
        record_id = cursor.lastrowid
        time_cursor = conn.execute("SELECT created_at FROM messages WHERE id = ?", (record_id,))
        created_at = time_cursor.fetchone()["created_at"]

    return MessageRecord(
        id=record_id,
        user_id=user_id,
        role=role,  # type: ignore[arg-type]
        content=content,
        tool_calls=tc_models,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        created_at=created_at,
    )


def get_recent_messages(
    user_id: int = 1,
    limit: int = 12,
    db_path: str = DEFAULT_DB_PATH,
) -> list[MessageRecord]:
    """Retrieve recent messages in chronological order."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT id, user_id, role, content, tool_calls, tool_call_id, tool_name, created_at
            FROM (
              SELECT * FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?
            ) ORDER BY id ASC
            """,
            (user_id, limit),
        )
        rows = cursor.fetchall()
        result: list[MessageRecord] = []
        for r in rows:
            tc_models = None
            if r["tool_calls"]:
                raw_tc = json.loads(r["tool_calls"])
                tc_models = [ToolCall.model_validate(tc) for tc in raw_tc]
            result.append(
                MessageRecord(
                    id=r["id"],
                    user_id=r["user_id"],
                    role=r["role"],
                    content=r["content"],
                    tool_calls=tc_models,
                    tool_call_id=r["tool_call_id"],
                    tool_name=r["tool_name"],
                    created_at=r["created_at"],
                )
            )
        return result


def clear_messages(user_id: int = 1, db_path: str = DEFAULT_DB_PATH) -> None:
    """Clear chat messages for a user."""
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))


# --- Unified get_logs helper (Section 8) ---


def get_logs(
    user_id: int = 1,
    type: str = "all",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    db_path: str = DEFAULT_DB_PATH,
) -> dict[str, list[Any]]:
    """Retrieve logs of specified type ('workout', 'meal', 'daily', or 'all')."""
    res: dict[str, list[Any]] = {}
    if type in ("workout", "all"):
        res["workouts"] = [w.model_dump() for w in get_workout_logs(user_id, start_date, end_date, limit=limit, db_path=db_path)]
    if type in ("meal", "all"):
        res["meals"] = [m.model_dump() for m in get_meal_logs(user_id, start_date, end_date, limit=limit, db_path=db_path)]
    if type in ("daily", "all"):
        res["daily"] = [d.model_dump() for d in get_daily_logs(user_id, start_date, end_date, limit=limit, db_path=db_path)]
    return res
