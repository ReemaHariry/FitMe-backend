"""
Workout Plan Generation Module

Generates personalized workout plans based on user profile data from Supabase.
Uses pure Python logic without external AI APIs.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List, Dict, Optional, Tuple
import logging

from app.routes.users import get_current_user
from app.services.supabase_service import get_profile

logger = logging.getLogger(__name__)
router = APIRouter()

# ============================================================================
# Data Models
# ============================================================================

class Exercise(BaseModel):
    name: str
    sets: int
    reps: str
    rest_sec: int
    muscle_group: str
    equipment: str
    tip: str


class DayPlan(BaseModel):
    day_name: str
    label: str
    is_rest: bool
    duration_min: int
    exercises: List[Exercise]
    warmup: List[str]
    cooldown: List[str]


class WorkoutPlanResponse(BaseModel):
    plan_title: str
    goal: str
    split: str
    level: str
    days_per_week: int
    weeks: int
    days: List[DayPlan]
    key_tips: List[str]
    nutrition_note: str


# ============================================================================
# Exercise Libraries
# ============================================================================

_CHEST = [
    ("Push-Up", "Chest / Triceps", "Bodyweight", 
     "Keep your body in a straight line; lower chest to 2 cm from floor."),
    ("Dumbbell Bench Press", "Chest / Triceps", "Dumbbells+Bench",
     "Retract shoulder blades; press to full extension without locking elbows."),
    ("Incline Dumbbell Press", "Upper Chest / Shoulders", "Dumbbells+Bench",
     "Set bench to 30-45°; press up and slightly inward at top."),
    ("Chest Dips", "Chest / Triceps", "Dip Bar",
     "Lean forward slightly; lower until shoulders are below elbows."),
]

_BACK = [
    ("Pull-Up", "Back / Biceps", "Pull-up Bar",
     "Pull until chin clears bar; control the descent."),
    ("Bent-Over Dumbbell Row", "Back / Biceps", "Dumbbells",
     "Hinge at hips; pull dumbbell to hip, keep elbow close to body."),
    ("Lat Pulldown", "Back / Biceps", "Cable Machine",
     "Pull bar to upper chest; squeeze shoulder blades together."),
    ("Inverted Row", "Back / Biceps", "Bar or TRX",
     "Keep body straight; pull chest to bar."),
]

_SHOULDERS = [
    ("Overhead Press", "Shoulders / Triceps", "Dumbbells or Barbell",
     "Press straight overhead; avoid arching lower back excessively."),
    ("Lateral Raise", "Side Delts", "Dumbbells",
     "Raise arms to shoulder height; slight bend in elbows."),
    ("Front Raise", "Front Delts", "Dumbbells",
     "Raise weight to eye level; control the movement."),
    ("Face Pull", "Rear Delts / Upper Back", "Cable or Band",
     "Pull to face height; externally rotate shoulders at peak."),
]

_LEGS = [
    ("Squat", "Quads / Glutes / Core", "Barbell or Bodyweight",
     "Keep chest up; knees track over toes; go to parallel or below."),
    ("Romanian Deadlift", "Hamstrings / Glutes / Lower Back", "Dumbbells or Barbell",
     "Hinge at hips; keep back neutral; feel stretch in hamstrings."),
    ("Lunges", "Quads / Glutes", "Bodyweight or Dumbbells",
     "Step forward; lower until back knee nearly touches ground."),
    ("Bulgarian Split Squat", "Quads / Glutes", "Dumbbells",
     "Rear foot elevated; lower until front thigh is parallel to ground."),
    ("Leg Press", "Quads / Glutes", "Leg Press Machine",
     "Press through heels; don't lock knees at top."),
]

_CORE = [
    ("Plank", "Core", "Bodyweight",
     "Keep body straight from head to heels; engage abs and glutes."),
    ("Dead Bug", "Core", "Bodyweight",
     "Lying on back; extend opposite arm and leg while keeping lower back pressed to floor."),
    ("Russian Twist", "Obliques / Core", "Bodyweight or Weight",
     "Seated with feet off ground; twist torso side to side."),
    ("Bicycle Crunch", "Core / Obliques", "Bodyweight",
     "Bring opposite elbow to opposite knee; control the movement."),
]

_CARDIO = [
    ("Treadmill Running", "Cardio", "Treadmill",
     "Maintain steady pace; gradually increase intensity."),
    ("Cycling", "Cardio / Legs", "Bike",
     "Maintain consistent cadence; adjust resistance as needed."),
    ("Rowing", "Full Body Cardio", "Rowing Machine",
     "Drive with legs first, then pull with arms; reverse on return."),
    ("Jump Rope", "Cardio / Coordination", "Jump Rope",
     "Stay on balls of feet; keep jumps low and quick."),
]

# Warmup exercises
_WARMUP = [
    "5 min light cardio (walking or jumping jacks)",
    "Arm circles — 10 forward, 10 backward",
    "Hip circles — 10 each direction",
    "Leg swings — 10 each leg",
    "Bodyweight squats — 10 reps",
]

# Cooldown exercises
_COOLDOWN = [
    "5 min easy walk",
    "Quad stretch — 30 sec each side",
    "Hamstring stretch — 30 sec each side",
    "Chest stretch (doorway) — 30 sec",
    "Child's pose — 60 sec",
]

# ============================================================================
# Goal Configuration
# ============================================================================

_GOAL_CFG: Dict[str, dict] = {
    "lose_weight": {
        "sets_compound": 3,
        "sets_isolation": 3,
        "reps_compound": "12-15",
        "reps_isolation": "15-20",
        "rest_compound": 60,
        "rest_isolation": 45,
        "note": "Stick to your calorie deficit. Combine this plan with 2-3 cardio sessions per week for best fat loss results."
    },
    "build_muscle": {
        "sets_compound": 4,
        "sets_isolation": 3,
        "reps_compound": "6-10",
        "reps_isolation": "10-12",
        "rest_compound": 120,
        "rest_isolation": 75,
        "note": "Eat 20-40 g of protein within 1 hour post-workout. Progressive overload is key — aim to add weight or reps each week."
    },
    "maintain": {
        "sets_compound": 3,
        "sets_isolation": 2,
        "reps_compound": "8-12",
        "reps_isolation": "12-15",
        "rest_compound": 90,
        "rest_isolation": 60,
        "note": "Match calories to your TDEE. Focus on movement quality and consistency rather than chasing maximal weights."
    }
}

# Days of the week
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# ============================================================================
# Helper Functions
# ============================================================================

def _make_exercise(ex_tuple: tuple, sets: int, reps: str, rest: int) -> Exercise:
    """Convert exercise tuple to Exercise object"""
    name, muscle, equip, tip = ex_tuple
    return Exercise(
        name=name,
        sets=sets,
        reps=reps,
        rest_sec=rest,
        muscle_group=muscle,
        equipment=equip,
        tip=tip
    )


def _select_exercises(muscle_group: str, count: int, cfg: dict) -> List[Exercise]:
    """Select exercises from a muscle group library"""
    libs = {
        "chest": _CHEST,
        "back": _BACK,
        "shoulders": _SHOULDERS,
        "legs": _LEGS,
        "core": _CORE,
        "cardio": _CARDIO,
    }
    
    lib = libs.get(muscle_group, [])
    selected = lib[:count] if lib else []
    
    exercises = []
    for ex_tuple in selected:
        name = ex_tuple[0]
        
        # Special handling for specific exercises
        if muscle_group == "cardio":
            exercises.append(_make_exercise(ex_tuple, 1, "20 min", 0))
        elif name in ["Plank", "Dead Bug"]:
            exercises.append(_make_exercise(ex_tuple, cfg["sets_isolation"], "30 sec", cfg["rest_isolation"]))
        elif muscle_group in ["chest", "back", "legs"]:
            # Primary compound movement
            exercises.append(_make_exercise(ex_tuple, cfg["sets_compound"], cfg["reps_compound"], cfg["rest_compound"]))
        else:
            # Isolation movements
            exercises.append(_make_exercise(ex_tuple, cfg["sets_isolation"], cfg["reps_isolation"], cfg["rest_isolation"]))
    
    return exercises


def _build_day(day_name: str, label: str, muscle_groups: List[str], cfg: dict, duration_min: int) -> DayPlan:
    """Build a training day with exercises from specified muscle groups"""
    exercises = []
    
    for mg in muscle_groups:
        # Primary muscle groups get 2 exercises, secondary get 1
        count = 2 if mg in ["chest", "back", "legs"] else 1
        exercises.extend(_select_exercises(mg, count, cfg))
    
    return DayPlan(
        day_name=day_name,
        label=label,
        is_rest=False,
        duration_min=duration_min,
        exercises=exercises,
        warmup=_WARMUP[:3],
        cooldown=_COOLDOWN[:4]
    )


def _rest_day(day_name: str) -> DayPlan:
    """Create a rest day"""
    return DayPlan(
        day_name=day_name,
        label="Rest & Recovery",
        is_rest=True,
        duration_min=0,
        exercises=[],
        warmup=[],
        cooldown=[]
    )


def _generate_plan(goal: str, days: int, duration: int) -> List[DayPlan]:
    """
    Generate a complete 7-day workout plan based on training frequency.
    
    Args:
        goal: "lose_weight", "build_muscle", or "maintain"
        days: Number of training days per week (1-6)
        duration: Target duration per session in minutes
    
    Returns:
        List of 7 DayPlan objects
    """
    cfg = _GOAL_CFG[goal]
    
    # Training split configurations
    splits: Dict[int, List[Tuple[str, List[str]]]] = {
        1: [
            ("Full Body", ["chest", "back", "legs", "shoulders", "core"])
        ],
        2: [
            ("Upper Body", ["chest", "back", "shoulders", "core"]),
            ("Lower Body", ["legs", "core", "cardio"])
        ],
        3: [
            ("Full Body A", ["chest", "back", "legs", "core"]),
            ("Full Body B", ["shoulders", "back", "legs", "core"]),
            ("Full Body C", ["chest", "legs", "core", "cardio"])
        ],
        4: [
            ("Upper Body A", ["chest", "back", "shoulders", "core"]),
            ("Lower Body A", ["legs", "core"]),
            ("Upper Body B", ["chest", "back", "shoulders", "core"]),
            ("Lower Body B", ["legs", "cardio", "core"])
        ],
        5: [
            ("Push", ["chest", "shoulders", "core"]),
            ("Pull", ["back", "core"]),
            ("Legs", ["legs", "core"]),
            ("Upper Body", ["chest", "back", "shoulders", "core"]),
            ("Legs + Cardio", ["legs", "cardio", "core"])
        ],
        6: [
            ("Push A", ["chest", "shoulders", "core"]),
            ("Pull A", ["back", "core"]),
            ("Legs A", ["legs", "core"]),
            ("Push B", ["chest", "shoulders", "core"]),
            ("Pull B", ["back", "core"]),
            ("Legs B", ["legs", "cardio"])
        ]
    }
    
    # Clamp days to 1-6
    days = max(1, min(6, days))
    
    workout_slots = splits[days]
    plan_days = []
    
    for i, weekday in enumerate(WEEKDAYS):
        if i < days:
            # Training day
            label, muscle_groups = workout_slots[i]
            plan_days.append(_build_day(weekday, label, muscle_groups, cfg, duration))
        else:
            # Rest day
            plan_days.append(_rest_day(weekday))
    
    return plan_days


# Split names for display
_SPLIT_NAMES = {
    1: "Full Body",
    2: "Upper / Lower",
    3: "Full Body ×3",
    4: "Upper / Lower ×2",
    5: "Push / Pull / Legs",
    6: "PPL ×2"
}

# Goal display names
_GOAL_NAMES = {
    "lose_weight": "Lose Weight",
    "build_muscle": "Build Muscle",
    "maintain": "Maintain Fitness"
}

# Key training tips by goal
_KEY_TIPS = {
    "lose_weight": [
        "Track your workouts and try to beat last week's performance",
        "Combine strength training with 2-3 cardio sessions per week",
        "Stay in a calorie deficit but keep protein intake high (1.6-2.2g per kg bodyweight)",
        "Rest at least 1 day between intense sessions to allow recovery"
    ],
    "build_muscle": [
        "Add 2.5 kg or 1 extra rep each week — progressive overload is essential",
        "Eat enough protein (1.6-2.2g per kg bodyweight daily)",
        "Get 7-9 hours of sleep for optimal muscle recovery",
        "Don't skip rest days — muscles grow during recovery, not during training"
    ],
    "maintain": [
        "Focus on consistency — 80% adherence beats 100% perfection for 2 weeks then quitting",
        "Listen to your body — if you're very fatigued, take an extra rest day",
        "Mix up exercises every 6-8 weeks to prevent plateaus and keep it interesting",
        "Maintain a balanced diet that matches your TDEE"
    ]
}

# ============================================================================
# API Endpoint
# ============================================================================

@router.get("/workout-plan", response_model=WorkoutPlanResponse)
async def get_workout_plan(
    level: str = Query("beginner", regex="^(beginner|intermediate|advanced)$"),
    current_user: dict = Depends(get_current_user)
):
    """
    Generate a personalized workout plan based on user profile.
    
    Query Parameters:
        level: User experience level (beginner, intermediate, advanced)
    
    Returns:
        WorkoutPlanResponse with 7-day plan, tips, and nutrition note
    """
    try:
        user_id = current_user["id"]
        
        # Fetch profile from database
        profile = get_profile(user_id)
        if not profile:
            raise HTTPException(
                status_code=404,
                detail="Profile not found. Please complete onboarding."
            )
        
        # Extract profile data with defaults
        goal = profile.get("fitness_goal") or "maintain"
        if goal not in ("lose_weight", "build_muscle", "maintain"):
            goal = "maintain"
        
        days = max(1, min(6, int(profile.get("training_days_per_week") or 3)))
        duration = int(profile.get("preferred_workout_duration") or 45)
        
        # Generate plan
        plan_days = _generate_plan(goal, days, duration)
        
        # Build response
        goal_display = _GOAL_NAMES[goal]
        split_name = _SPLIT_NAMES[days]
        plan_title = f"{goal_display} — {split_name} Plan"
        
        return WorkoutPlanResponse(
            plan_title=plan_title,
            goal=goal_display,
            split=split_name,
            level=level.capitalize(),
            days_per_week=days,
            weeks=8,
            days=plan_days,
            key_tips=_KEY_TIPS[goal],
            nutrition_note=_GOAL_CFG[goal]["note"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Workout plan generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
