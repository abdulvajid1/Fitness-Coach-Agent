"""Pydantic models for data validation and representation."""

from __future__ import annotations

import json
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


# --- Profile & Notes ---

GoalType = Literal["fat_loss", "muscle_gain", "general_fitness"]
NoteCategory = Literal["injury", "equipment", "diet", "preference", "schedule", "other"]


class UserProfile(BaseModel):
    """User profile data stored in the database."""

    id: int = 1
    name: str | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    goal: str | None = None
    onboarding_done: bool = False

    @property
    def missing_fields(self) -> list[str]:
        """Return list of missing required profile fields."""
        missing = []
        if not self.name or not self.name.strip():
            missing.append("name")
        if self.height_cm is None or self.height_cm <= 0:
            missing.append("height_cm")
        if self.weight_kg is None or self.weight_kg <= 0:
            missing.append("weight_kg")
        if not self.goal or not self.goal.strip():
            missing.append("goal")
        return missing


class UserNote(BaseModel):
    """Durable long-term memory note."""

    id: int | None = None
    user_id: int = 1
    category: str
    content: str
    active: bool = True

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        valid = {"injury", "equipment", "diet", "preference", "schedule", "other"}
        if v.lower() not in valid:
            raise ValueError(f"Category must be one of {sorted(valid)}, got '{v}'")
        return v.lower()


# --- Workout Plan Format (Section 6) ---


class ExercisePlan(BaseModel):
    """Individual exercise in a workout plan."""

    name: str
    sets: int
    reps_min: int
    reps_max: int
    weight_kg: float | None = None

    @field_validator("sets")
    @classmethod
    def validate_sets(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Sets must be greater than 0")
        return v

    @field_validator("reps_min")
    @classmethod
    def validate_reps_min(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("reps_min must be greater than 0")
        return v

    @model_validator(mode="after")
    def validate_rep_range(self) -> ExercisePlan:
        if self.reps_max < self.reps_min:
            raise ValueError(f"reps_max ({self.reps_max}) cannot be less than reps_min ({self.reps_min})")
        if self.weight_kg is not None and self.weight_kg < 0:
            raise ValueError("weight_kg cannot be negative")
        return self


class DayPlan(BaseModel):
    """Daily schedule within a workout plan."""

    day: str
    focus: str
    exercises: list[ExercisePlan] = Field(default_factory=list)

    @field_validator("exercises")
    @classmethod
    def validate_exercises(cls, v: list[ExercisePlan]) -> list[ExercisePlan]:
        if not v:
            raise ValueError("Each day plan must contain at least one exercise")
        return v


class WorkoutPlanSchema(BaseModel):
    """Complete weekly workout plan."""

    days: list[DayPlan] = Field(default_factory=list)

    @field_validator("days")
    @classmethod
    def validate_days(cls, v: list[DayPlan]) -> list[DayPlan]:
        if not v:
            raise ValueError("Workout plan must contain at least one day")
        return v


class WorkoutPlanRecord(BaseModel):
    """Database record for workout plans."""

    id: int | None = None
    user_id: int = 1
    version: int
    is_active: bool = True
    plan_json: str
    plan: WorkoutPlanSchema | None = None

    @model_validator(mode="after")
    def parse_plan(self) -> WorkoutPlanRecord:
        if self.plan is None and self.plan_json:
            data = json.loads(self.plan_json)
            self.plan = WorkoutPlanSchema.model_validate(data)
        return self


# --- Logs ---


class WorkoutSet(BaseModel):
    """A single set within a workout session log."""

    set_number: int | None = None
    reps: int
    weight_kg: float | None = None
    rpe: float | None = None

    @field_validator("reps")
    @classmethod
    def validate_reps(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Reps cannot be negative")
        return v

    @field_validator("rpe")
    @classmethod
    def validate_rpe(cls, v: float | None) -> float | None:
        if v is not None and not (1.0 <= v <= 10.0):
            raise ValueError("RPE must be between 1 and 10")
        return v


class WorkoutLogRecord(BaseModel):
    """Database record for a workout log entry."""

    id: int | None = None
    user_id: int = 1
    date: str  # YYYY-MM-DD
    exercise: str
    set_number: int | None = None
    reps: int
    weight_kg: float | None = None
    rpe: float | None = None


class MealLogRecord(BaseModel):
    """Database record for a meal log entry."""

    id: int | None = None
    user_id: int = 1
    date: str  # YYYY-MM-DD
    description: str
    calories: float | None = None
    protein_g: float | None = None


class DailyLogRecord(BaseModel):
    """Database record for daily wellness metrics."""

    id: int | None = None
    user_id: int = 1
    date: str  # YYYY-MM-DD
    sleep_hours: float | None = None
    energy: int | None = None  # 1-10
    notes: str | None = None

    @field_validator("energy")
    @classmethod
    def validate_energy(cls, v: int | None) -> int | None:
        if v is not None and not (1 <= v <= 10):
            raise ValueError("Energy must be between 1 and 10")
        return v

    @field_validator("sleep_hours")
    @classmethod
    def validate_sleep(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("Sleep hours cannot be negative")
        return v


# --- Messages & Neutral Format (Section 4.1) ---


class ToolCall(BaseModel):
    """Neutral representation of a tool call."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class MessageRecord(BaseModel):
    """Neutral message format stored in database and used throughout app."""

    id: int | None = None
    user_id: int = 1
    role: Literal["user", "assistant", "tool", "system"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    created_at: str | None = None

    def to_neutral_dict(self) -> dict[str, Any]:
        """Convert to neutral dict format per Section 4.1."""
        d: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
            "tool_calls": (
                [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in self.tool_calls]
                if self.tool_calls is not None
                else None
            ),
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
        }
        return d

