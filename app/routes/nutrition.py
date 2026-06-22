"""
Nutrition Planner Module

Calculates calorie needs and generates meal plans based on user data.
Uses Mifflin-St Jeor equation for BMR and provides goal-specific meal plans.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional
import logging

from app.routes.users import get_current_user
from app.services.supabase_service import get_profile

logger = logging.getLogger(__name__)
router = APIRouter()

# ============================================================================
# MODELS
# ============================================================================

class CalorieRequest(BaseModel):
    gender: str = Field(..., pattern="^(male|female)$")
    age: int = Field(..., ge=13, le=100)
    height: float = Field(..., ge=100, le=250)
    weight: float = Field(..., ge=30, le=300)
    activity_level: str = Field(
        ...,
        pattern="^(sedentary|light|moderate|active|very_active)$"
    )
    goal: str = Field(..., pattern="^(lose_weight|build_muscle|maintain)$")


class CalorieResponse(BaseModel):
    bmr: float
    tdee: float
    target_calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    goal: str
    bmi: float
    bmi_category: str


class ProfileData(BaseModel):
    gender: str
    age: int
    height: float
    weight: float
    fitness_goal: str
    full_name: Optional[str]
    training_days_per_week: Optional[int]
    activity_level: str  # 🔥 FIX: was missing, so the frontend never received it


class AutoCalorieResponse(BaseModel):
    profile: ProfileData
    calories: CalorieResponse


# ============================================================================
# CORE CALCULATION
# ============================================================================

def calculate_calories(data: CalorieRequest) -> CalorieResponse:

    # BMR (Mifflin-St Jeor)
    if data.gender == "male":
        bmr = 10 * data.weight + 6.25 * data.height - 5 * data.age + 5
    else:
        bmr = 10 * data.weight + 6.25 * data.height - 5 * data.age - 161

    activity_multipliers = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "active": 1.725,
        "very_active": 1.9,
    }

    tdee = bmr * activity_multipliers[data.activity_level]

    if data.goal == "lose_weight":
        target = tdee - 500
        protein_pct, carbs_pct, fat_pct = 0.35, 0.35, 0.30
    elif data.goal == "build_muscle":
        target = tdee + 300
        protein_pct, carbs_pct, fat_pct = 0.30, 0.45, 0.25
    else:
        target = tdee
        protein_pct, carbs_pct, fat_pct = 0.25, 0.50, 0.25

    protein_g = (target * protein_pct) / 4
    carbs_g = (target * carbs_pct) / 4
    fat_g = (target * fat_pct) / 9

    height_m = data.height / 100
    bmi = data.weight / (height_m ** 2)

    if bmi < 18.5:
        bmi_category = "Underweight"
    elif bmi < 25:
        bmi_category = "Normal"
    elif bmi < 30:
        bmi_category = "Overweight"
    else:
        bmi_category = "Obese"

    return CalorieResponse(
        bmr=round(bmr, 1),
        tdee=round(tdee, 1),
        target_calories=round(target, 1),
        protein_g=round(protein_g, 1),
        carbs_g=round(carbs_g, 1),
        fat_g=round(fat_g, 1),
        goal=data.goal,
        bmi=round(bmi, 1),
        bmi_category=bmi_category
    )


# ============================================================================
# ACTIVITY DERIVATION LOGIC
# ============================================================================

def derive_activity_level(training_days: int | None) -> str:
    if training_days is None:
        return "moderate"

    if training_days <= 1:
        return "sedentary"
    elif training_days <= 3:
        return "light"
    elif training_days <= 5:
        return "moderate"
    elif training_days <= 6:
        return "active"
    else:
        return "very_active"


# ============================================================================
# PROFILE CONVERSION
# ============================================================================

def profile_to_request(profile: dict, activity_level: str) -> CalorieRequest:

    gender = profile.get("gender") or "male"
    goal = profile.get("fitness_goal") or "maintain"

    return CalorieRequest(
        gender=gender,
        age=int(profile.get("age") or 25),
        height=float(profile.get("height") or 170),
        weight=float(profile.get("weight") or 70),
        activity_level=activity_level,
        goal=goal,
    )


# ============================================================================
# API
# ============================================================================

@router.get("/nutrition/calculate-from-profile", response_model=AutoCalorieResponse)
async def calculate_from_profile(
    current_user: dict = Depends(get_current_user)
):
    """
    Automatically calculate calories from DB profile.
    Activity level is derived from training_days_per_week.
    """

    try:
        user_id = current_user["id"]
        profile = get_profile(user_id)

        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")

        # AUTO derive activity from training days
        activity_level = derive_activity_level(
            profile.get("training_days_per_week")
        )

        calc_request = profile_to_request(profile, activity_level)
        calorie_result = calculate_calories(calc_request)

        profile_data = ProfileData(
            gender=profile.get("gender") or "male",
            age=profile.get("age") or 25,
            height=profile.get("height") or 170,
            weight=profile.get("weight") or 70,
            fitness_goal=profile.get("fitness_goal") or "maintain",
            full_name=profile.get("full_name"),
            training_days_per_week=profile.get("training_days_per_week"),
            activity_level=activity_level,  # 🔥 FIX: actually send the derived value back
        )

        return AutoCalorieResponse(
            profile=profile_data,
            calories=calorie_result
        )

    except Exception as e:
        logger.error(f"Profile calculation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))