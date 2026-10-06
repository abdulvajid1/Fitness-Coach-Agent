"""Tests for SQLite database schema, CRUD operations, and Pydantic models."""

import pytest
from fitness_coach_agent.db import (
    clear_messages,
    get_active_notes,
    get_active_plan,
    get_daily_log,
    get_daily_logs,
    get_logs,
    get_meal_logs,
    get_or_create_user,
    get_plan_history,
    get_recent_messages,
    get_user,
    get_workout_logs,
    init_db,
    log_daily,
    log_meal,
    log_workout,
    save_message,
    save_note,
    save_plan,
    update_note,
    update_user_profile,
)
from fitness_coach_agent.models import (
    DayPlan,
    ExercisePlan,
    ToolCall,
    UserProfile,
    WorkoutPlanSchema,
)


@pytest.fixture
def test_db(tmp_path):
    """Fixture to provide a clean temporary SQLite database."""
    db_file = tmp_path / "test_fitness.db"
    init_db(str(db_file))
    return str(db_file)


# --- 1. User & Partial Onboarding Tests ---


def test_user_creation_and_partial_onboarding(test_db):
    user = get_or_create_user(user_id=1, db_path=test_db)
    assert user.id == 1
    assert user.onboarding_done is False
    assert set(user.missing_fields) == {"name", "height_cm", "weight_kg", "goal"}

    # Update name only (partial onboarding)
    user = update_user_profile(user_id=1, name="Alex", db_path=test_db)
    assert user.name == "Alex"
    assert set(user.missing_fields) == {"height_cm", "weight_kg", "goal"}

    # Simulate resuming in a new session
    resumed_user = get_user(user_id=1, db_path=test_db)
    assert resumed_user is not None
    assert resumed_user.name == "Alex"

    # Complete the rest of the profile
    user = update_user_profile(
        user_id=1,
        height_cm=178.5,
        weight_kg=75.0,
        goal="muscle_gain",
        onboarding_done=True,
        db_path=test_db,
    )
    assert user.height_cm == 178.5
    assert user.weight_kg == 75.0
    assert user.goal == "muscle_gain"
    assert user.onboarding_done is True
    assert user.missing_fields == []


# --- 2. User Notes Tests ---


def test_user_notes_crud_and_validation(test_db):
    note = save_note(
        user_id=1,
        category="injury",
        content="Lower back strain on deadlifts",
        db_path=test_db,
    )
    assert note.id is not None
    assert note.category == "injury"
    assert note.active is True

    # Add second note
    save_note(user_id=1, category="equipment", content="Only dumbbells available", db_path=test_db)

    active_notes = get_active_notes(user_id=1, db_path=test_db)
    assert len(active_notes) == 2

    # Deactivate the first note
    updated = update_note(note_id=note.id, user_id=1, active=False, db_path=test_db)
    assert updated is not None
    assert updated.active is False

    active_remaining = get_active_notes(user_id=1, db_path=test_db)
    assert len(active_remaining) == 1
    assert active_remaining[0].category == "equipment"

    # Category validation test
    with pytest.raises(ValueError):
        save_note(user_id=1, category="invalid_category", content="test", db_path=test_db)


# --- 3. Workout Plan Tests & Versioning ---


def test_workout_plan_validation_and_versioning(test_db):
    valid_plan = {
        "days": [
            {
                "day": "Monday",
                "focus": "Push",
                "exercises": [
                    {
                        "name": "Bench Press",
                        "sets": 3,
                        "reps_min": 8,
                        "reps_max": 12,
                        "weight_kg": 40.0,
                    }
                ],
            }
        ]
    }

    # Version 1
    p1 = save_plan(user_id=1, plan=valid_plan, db_path=test_db)
    assert p1.version == 1
    assert p1.is_active is True

    active = get_active_plan(user_id=1, db_path=test_db)
    assert active is not None
    assert active.version == 1
    assert active.plan.days[0].exercises[0].name == "Bench Press"

    # Version 2 update
    updated_plan = {
        "days": [
            {
                "day": "Monday",
                "focus": "Push",
                "exercises": [
                    {
                        "name": "Bench Press",
                        "sets": 4,
                        "reps_min": 8,
                        "reps_max": 12,
                        "weight_kg": 42.5,
                    }
                ],
            }
        ]
    }
    p2 = save_plan(user_id=1, plan=updated_plan, db_path=test_db)
    assert p2.version == 2
    assert p2.is_active is True

    # Check active plan is now v2
    active_now = get_active_plan(user_id=1, db_path=test_db)
    assert active_now.version == 2
    assert active_now.plan.days[0].exercises[0].sets == 4

    # Check version history has both
    history = get_plan_history(user_id=1, db_path=test_db)
    assert len(history) == 2
    assert history[0].version == 1
    assert history[0].is_active is False
    assert history[1].version == 2
    assert history[1].is_active is True


def test_workout_plan_invalid_structures(test_db):
    # Invalid: reps_max < reps_min
    with pytest.raises(ValueError):
        save_plan(
            user_id=1,
            plan={
                "days": [
                    {
                        "day": "Monday",
                        "focus": "Legs",
                        "exercises": [{"name": "Squat", "sets": 3, "reps_min": 10, "reps_max": 5}],
                    }
                ]
            },
            db_path=test_db,
        )

    # Invalid: empty exercises
    with pytest.raises(ValueError):
        save_plan(
            user_id=1,
            plan={"days": [{"day": "Monday", "focus": "Rest", "exercises": []}]},
            db_path=test_db,
        )

    # Invalid: empty days
    with pytest.raises(ValueError):
        save_plan(user_id=1, plan={"days": []}, db_path=test_db)


# --- 4. Workout Logs Tests ---


def test_workout_logs(test_db):
    sets = [
        {"reps": 10, "weight_kg": 50.0, "rpe": 8.0},
        {"reps": 9, "weight_kg": 50.0, "rpe": 8.5},
    ]
    records = log_workout(user_id=1, date="2026-10-01", exercise="Squat", sets=sets, db_path=test_db)
    assert len(records) == 2
    assert records[0].set_number == 1
    assert records[1].set_number == 2

    # Append another set later in the same day
    more_sets = [{"reps": 8, "weight_kg": 50.0, "rpe": 9.0}]
    rec2 = log_workout(user_id=1, date="2026-10-01", exercise="Squat", sets=more_sets, db_path=test_db)
    assert rec2[0].set_number == 3

    # Retrieve and filter
    logs = get_workout_logs(user_id=1, start_date="2026-10-01", end_date="2026-10-01", exercise="Squat", db_path=test_db)
    assert len(logs) == 3


# --- 5. Meal Logs Tests ---


def test_meal_logs(test_db):
    m1 = log_meal(user_id=1, date="2026-10-01", description="Oatmeal with whey", calories=450, protein_g=35, db_path=test_db)
    assert m1.id is not None
    assert m1.calories == 450

    m2 = log_meal(user_id=1, date="2026-10-02", description="Chicken salad", calories=600, protein_g=50, db_path=test_db)

    meals = get_meal_logs(user_id=1, start_date="2026-10-01", end_date="2026-10-01", db_path=test_db)
    assert len(meals) == 1
    assert meals[0].description == "Oatmeal with whey"


# --- 6. Daily Logs & Upsert Tests ---


def test_daily_logs_upsert(test_db):
    # Log sleep in the morning
    d1 = log_daily(user_id=1, date="2026-10-01", sleep_hours=7.5, db_path=test_db)
    assert d1.sleep_hours == 7.5
    assert d1.energy is None

    # Log energy & notes in the evening (upsert should preserve sleep_hours)
    d2 = log_daily(user_id=1, date="2026-10-01", energy=8, notes="Felt great", db_path=test_db)
    assert d2.sleep_hours == 7.5
    assert d2.energy == 8
    assert d2.notes == "Felt great"

    # Only one row exists for that date
    logs = get_daily_logs(user_id=1, start_date="2026-10-01", end_date="2026-10-01", db_path=test_db)
    assert len(logs) == 1

    # Validation: energy between 1 and 10
    with pytest.raises(ValueError):
        log_daily(user_id=1, date="2026-10-02", energy=15, db_path=test_db)


# --- 7. Messages & Neutral Format Tests ---


def test_messages_neutral_format(test_db):
    # 1. User message
    m1 = save_message(user_id=1, role="user", content="Calculate my BMI", db_path=test_db)
    assert m1.id is not None
    assert m1.role == "user"

    # 2. Assistant message with tool call
    tool_calls = [
        {"id": "call_123", "name": "calculator", "arguments": {"expression": "75 / (1.78 ** 2)"}}
    ]
    m2 = save_message(
        user_id=1,
        role="assistant",
        content=None,
        tool_calls=tool_calls,
        db_path=test_db,
    )
    assert m2.tool_calls is not None
    assert len(m2.tool_calls) == 1
    assert m2.tool_calls[0].id == "call_123"

    # 3. Tool result message
    m3 = save_message(
        user_id=1,
        role="tool",
        content="23.67",
        tool_call_id="call_123",
        tool_name="calculator",
        db_path=test_db,
    )
    assert m3.tool_call_id == "call_123"
    assert m3.tool_name == "calculator"

    # Retrieve recent messages in chronological order
    recent = get_recent_messages(user_id=1, limit=10, db_path=test_db)
    assert len(recent) == 3
    assert recent[0].role == "user"
    assert recent[1].role == "assistant"
    assert recent[2].role == "tool"

    neutral_dict = recent[1].to_neutral_dict()
    assert neutral_dict["role"] == "assistant"
    assert neutral_dict["tool_calls"][0]["name"] == "calculator"

    # Clear messages
    clear_messages(user_id=1, db_path=test_db)
    assert len(get_recent_messages(user_id=1, db_path=test_db)) == 0


# --- 8. Unified get_logs Tests ---


def test_unified_get_logs(test_db):
    log_workout(user_id=1, date="2026-10-05", exercise="Pushup", sets=[{"reps": 20}], db_path=test_db)
    log_meal(user_id=1, date="2026-10-05", description="Apple", calories=95, db_path=test_db)
    log_daily(user_id=1, date="2026-10-05", sleep_hours=8.0, energy=7, db_path=test_db)

    all_logs = get_logs(user_id=1, type="all", start_date="2026-10-05", end_date="2026-10-05", db_path=test_db)
    assert len(all_logs["workouts"]) == 1
    assert len(all_logs["meals"]) == 1
    assert len(all_logs["daily"]) == 1

