"""
Nutrition Planner Module

Calculates calorie needs and generates meal plans based on user data.
Uses Mifflin-St Jeor equation for BMR and provides goal-specific meal plans.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
import logging

from app.routes.users import get_current_user
from app.services.supabase_service import get_profile

logger = logging.getLogger(__name__)
router = APIRouter()

# ============================================================================
# Data Models
# ============================================================================

class CalorieRequest(BaseModel):
    gender: str = Field(..., pattern="^(male|female)$")
    age: int = Field(..., ge=13, le=100)
    height: float = Field(..., ge=100, le=250, description="Height in cm")
    weight: float = Field(..., ge=30, le=300, description="Weight in kg")
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


class MealItem(BaseModel):
    name: str
    calories: int
    protein_g: float
    carbs_g: float
    fat_g: float
    portion: str


class DayMeals(BaseModel):
    day: str
    breakfast: MealItem
    morning_snack: MealItem
    lunch: MealItem
    afternoon_snack: MealItem
    dinner: MealItem
    total_calories: int


class NutritionPlanResponse(BaseModel):
    plan_name: str
    daily_calories: int
    weekly_plan: List[DayMeals]
    tips: List[str]
    foods_to_eat: List[str]
    foods_to_avoid: List[str]


class ProfileData(BaseModel):
    gender: str
    age: int
    height: float
    weight: float
    fitness_goal: str
    full_name: Optional[str]
    training_days_per_week: Optional[int]
    preferred_workout_duration: Optional[int]


class AutoCalorieResponse(BaseModel):
    profile: ProfileData
    calories: CalorieResponse


class AutoPlanResponse(BaseModel):
    profile: ProfileData
    calories: CalorieResponse
    plan: NutritionPlanResponse


# ============================================================================
# Core Calculation Functions
# ============================================================================

def calculate_calories(data: CalorieRequest) -> CalorieResponse:
    """
    Calculate BMR, TDEE, target calories, and macronutrients.
    
    Uses Mifflin-St Jeor equation for BMR calculation.
    """
    # BMR calculation using Mifflin-St Jeor
    if data.gender == "male":
        bmr = 10 * data.weight + 6.25 * data.height - 5 * data.age + 5
    else:
        bmr = 10 * data.weight + 6.25 * data.height - 5 * data.age - 161
    
    # Activity multipliers for TDEE
    activity_multipliers = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "active": 1.725,
        "very_active": 1.9,
    }
    tdee = bmr * activity_multipliers[data.activity_level]
    
    # Goal-based calorie adjustments
    if data.goal == "lose_weight":
        target = tdee - 500  # ~0.5kg/week deficit
    elif data.goal == "build_muscle":
        target = tdee + 300  # lean bulk surplus
    else:
        target = tdee
    
    # Macro distribution by goal
    if data.goal == "lose_weight":
        protein_pct, carbs_pct, fat_pct = 0.35, 0.35, 0.30
    elif data.goal == "build_muscle":
        protein_pct, carbs_pct, fat_pct = 0.30, 0.45, 0.25
    else:
        protein_pct, carbs_pct, fat_pct = 0.25, 0.50, 0.25
    
    # Convert to grams
    protein_g = (target * protein_pct) / 4
    carbs_g = (target * carbs_pct) / 4
    fat_g = (target * fat_pct) / 9
    
    # Calculate BMI
    height_m = data.height / 100
    bmi = data.weight / (height_m ** 2)
    
    # BMI category
    if bmi < 18.5:
        bmi_category = "Underweight"
    elif bmi < 25:
        bmi_category = "Normal weight"
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


def generate_nutrition_plan(calories: float, goal: str, gender: str) -> NutritionPlanResponse:
    """
    Generate a 7-day meal plan with 5 meals per day.
    
    Args:
        calories: Target daily calories
        goal: lose_weight, build_muscle, or maintain
        gender: male or female (for portion adjustments)
    
    Returns:
        NutritionPlanResponse with weekly plan and guidance
    """
    # Meal calorie distribution
    b_cal = int(calories * 0.25)  # Breakfast: 25%
    ms_cal = int(calories * 0.10)  # Morning snack: 10%
    l_cal = int(calories * 0.35)  # Lunch: 35%
    as_cal = int(calories * 0.10)  # Afternoon snack: 10%
    d_cal = int(calories * 0.20)  # Dinner: 20%
    
    # Goal-specific meal templates
    if goal == "lose_weight":
        plan_name = "Fat Loss Nutrition Plan"
        weekly_meals = _generate_fat_loss_meals(b_cal, ms_cal, l_cal, as_cal, d_cal)
        tips = [
            "Drink 8-10 glasses of water daily to support metabolism and reduce hunger",
            "Eat protein with every meal to preserve muscle mass during fat loss",
            "Include fibrous vegetables to increase satiety while staying in deficit",
            "Plan meals ahead to avoid impulsive high-calorie choices",
            "Allow one flexible meal per week to maintain adherence"
        ]
        foods_to_eat = [
            "Lean meats", "Leafy greens", "Berries", "Eggs",
            "Greek yogurt", "Legumes", "Quinoa", "Salmon"
        ]
        foods_to_avoid = [
            "Fried foods", "Sugary drinks", "White bread",
            "Processed snacks", "Alcohol", "Full-fat dairy (excess)"
        ]
    
    elif goal == "build_muscle":
        plan_name = "Muscle Building Nutrition Plan"
        weekly_meals = _generate_muscle_building_meals(b_cal, ms_cal, l_cal, as_cal, d_cal)
        tips = [
            "Eat every 3-4 hours to keep muscles fueled throughout the day",
            "Consume 25-40g protein within 45 minutes post-workout for optimal recovery",
            "Include complex carbs around training to fuel performance and recovery",
            "Don't fear healthy fats — they support hormone production for muscle growth",
            "Track your weight weekly and adjust calories if not gaining 0.25-0.5kg per week"
        ]
        foods_to_eat = [
            "Chicken breast", "Eggs", "Salmon", "Lean beef",
            "Whole milk", "Oats", "Brown rice", "Sweet potato",
            "Avocado", "Nuts"
        ]
        foods_to_avoid = [
            "Excessive alcohol", "Ultra-processed foods", "Refined sugar",
            "Fast food (regularly)", "Diet sodas (they suppress appetite)"
        ]
    
    else:  # maintain
        plan_name = "Maintenance & Balanced Nutrition Plan"
        weekly_meals = _generate_maintenance_meals(b_cal, ms_cal, l_cal, as_cal, d_cal)
        tips = [
            "Focus on whole, minimally processed foods 80% of the time",
            "Listen to hunger and fullness cues rather than strict calorie counting",
            "Include variety in your diet to ensure adequate micronutrient intake",
            "Stay hydrated and prioritize sleep for overall health",
            "Enjoy social meals without guilt — consistency matters more than perfection"
        ]
        foods_to_eat = [
            "Whole grains", "Colorful vegetables", "Lean proteins",
            "Healthy fats", "Legumes", "Fruits", "Fermented foods"
        ]
        foods_to_avoid = [
            "Ultra-processed snacks", "Excess sodium", "Trans fats",
            "Excessive sugar", "Binge drinking"
        ]
    
    return NutritionPlanResponse(
        plan_name=plan_name,
        daily_calories=int(calories),
        weekly_plan=weekly_meals,
        tips=tips,
        foods_to_eat=foods_to_eat,
        foods_to_avoid=foods_to_avoid
    )


# ============================================================================
# Meal Generation Functions
# ============================================================================

def _generate_fat_loss_meals(b_cal, ms_cal, l_cal, as_cal, d_cal) -> List[DayMeals]:
    """Generate 7-day fat loss meal plan"""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    meals = []
    
    # Template meals with macros
    breakfast_options = [
        MealItem(
            name="Greek yogurt with berries & chia seeds",
            calories=b_cal,
            protein_g=18,
            carbs_g=30,
            fat_g=5,
            portion="200g yogurt + 100g berries"
        ),
        MealItem(
            name="Egg white omelet with vegetables",
            calories=b_cal,
            protein_g=25,
            carbs_g=15,
            fat_g=8,
            portion="5 egg whites + peppers, spinach, tomatoes"
        ),
        MealItem(
            name="Overnight oats with protein powder",
            calories=b_cal,
            protein_g=20,
            carbs_g=35,
            fat_g=6,
            portion="50g oats + 1 scoop protein + almond milk"
        )
    ]
    
    snack_options = [
        MealItem(
            name="Apple with almond butter",
            calories=ms_cal,
            protein_g=4,
            carbs_g=20,
            fat_g=8,
            portion="1 medium apple + 1 tbsp almond butter"
        ),
        MealItem(
            name="Protein shake",
            calories=ms_cal,
            protein_g=25,
            carbs_g=5,
            fat_g=2,
            portion="1 scoop whey + water"
        )
    ]
    
    lunch_options = [
        MealItem(
            name="Grilled chicken salad with olive oil dressing",
            calories=l_cal,
            protein_g=35,
            carbs_g=25,
            fat_g=15,
            portion="150g chicken + mixed greens + 1 tbsp olive oil"
        ),
        MealItem(
            name="Turkey & avocado wrap (whole wheat)",
            calories=l_cal,
            protein_g=30,
            carbs_g=35,
            fat_g=12,
            portion="100g turkey + 1/4 avocado + whole wheat tortilla"
        ),
        MealItem(
            name="Tuna salad with quinoa",
            calories=l_cal,
            protein_g=32,
            carbs_g=30,
            fat_g=10,
            portion="1 can tuna + 80g quinoa + vegetables"
        )
    ]
    
    dinner_options = [
        MealItem(
            name="Baked salmon with steamed broccoli",
            calories=d_cal,
            protein_g=28,
            carbs_g=15,
            fat_g=12,
            portion="120g salmon + 200g broccoli"
        ),
        MealItem(
            name="Lean beef stir-fry with vegetables",
            calories=d_cal,
            protein_g=30,
            carbs_g=20,
            fat_g=10,
            portion="100g lean beef + mixed vegetables"
        )
    ]
    
    # Build 7-day plan
    for i, day in enumerate(days):
        total = b_cal + ms_cal + l_cal + as_cal + d_cal
        meals.append(DayMeals(
            day=day,
            breakfast=breakfast_options[i % len(breakfast_options)],
            morning_snack=snack_options[i % len(snack_options)],
            lunch=lunch_options[i % len(lunch_options)],
            afternoon_snack=snack_options[(i+1) % len(snack_options)],
            dinner=dinner_options[i % len(dinner_options)],
            total_calories=total
        ))
    
    return meals


def _generate_muscle_building_meals(b_cal, ms_cal, l_cal, as_cal, d_cal) -> List[DayMeals]:
    """Generate 7-day muscle building meal plan"""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    meals = []
    
    breakfast_options = [
        MealItem(
            name="5-egg omelet with cheese & vegetables",
            calories=b_cal,
            protein_g=35,
            carbs_g=15,
            fat_g=22,
            portion="5 eggs + 50g cheese"
        ),
        MealItem(
            name="Protein pancakes with peanut butter",
            calories=b_cal,
            protein_g=30,
            carbs_g=45,
            fat_g=18,
            portion="3 pancakes + 2 tbsp peanut butter"
        ),
        MealItem(
            name="Oatmeal with whole milk & whey protein",
            calories=b_cal,
            protein_g=32,
            carbs_g=50,
            fat_g=15,
            portion="80g oats + 300ml milk + 1 scoop protein"
        )
    ]
    
    snack_options = [
        MealItem(
            name="Mass gainer shake",
            calories=ms_cal,
            protein_g=25,
            carbs_g=40,
            fat_g=8,
            portion="1 scoop protein + banana + oats + milk"
        ),
        MealItem(
            name="Trail mix & protein bar",
            calories=ms_cal,
            protein_g=20,
            carbs_g=35,
            fat_g=12,
            portion="50g nuts + 1 protein bar"
        )
    ]
    
    lunch_options = [
        MealItem(
            name="Chicken breast with brown rice & avocado",
            calories=l_cal,
            protein_g=40,
            carbs_g=60,
            fat_g=18,
            portion="200g chicken + 150g rice + 1/2 avocado"
        ),
        MealItem(
            name="Beef burrito bowl",
            calories=l_cal,
            protein_g=38,
            carbs_g=55,
            fat_g=20,
            portion="150g beef + rice + beans + cheese"
        )
    ]
    
    dinner_options = [
        MealItem(
            name="Salmon with sweet potato & asparagus",
            calories=d_cal,
            protein_g=32,
            carbs_g=35,
            fat_g=15,
            portion="150g salmon + 200g sweet potato"
        ),
        MealItem(
            name="Lean steak with quinoa",
            calories=d_cal,
            protein_g=35,
            carbs_g=30,
            fat_g=18,
            portion="150g steak + 100g quinoa"
        )
    ]
    
    for i, day in enumerate(days):
        total = b_cal + ms_cal + l_cal + as_cal + d_cal
        meals.append(DayMeals(
            day=day,
            breakfast=breakfast_options[i % len(breakfast_options)],
            morning_snack=snack_options[i % len(snack_options)],
            lunch=lunch_options[i % len(lunch_options)],
            afternoon_snack=snack_options[(i+1) % len(snack_options)],
            dinner=dinner_options[i % len(dinner_options)],
            total_calories=total
        ))
    
    return meals


def _generate_maintenance_meals(b_cal, ms_cal, l_cal, as_cal, d_cal) -> List[DayMeals]:
    """Generate 7-day maintenance meal plan"""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    meals = []
    
    breakfast_options = [
        MealItem(
            name="Whole grain toast with eggs & avocado",
            calories=b_cal,
            protein_g=20,
            carbs_g=35,
            fat_g=15,
            portion="2 slices toast + 2 eggs + 1/4 avocado"
        ),
        MealItem(
            name="Smoothie bowl with mixed toppings",
            calories=b_cal,
            protein_g=18,
            carbs_g=40,
            fat_g=12,
            portion="Banana, berries, protein, granola"
        )
    ]
    
    snack_options = [
        MealItem(
            name="Greek yogurt with honey",
            calories=ms_cal,
            protein_g=15,
            carbs_g=20,
            fat_g=5,
            portion="150g yogurt + 1 tsp honey"
        ),
        MealItem(
            name="Hummus with vegetables",
            calories=ms_cal,
            protein_g=8,
            carbs_g=18,
            fat_g=8,
            portion="60g hummus + carrots, peppers"
        )
    ]
    
    lunch_options = [
        MealItem(
            name="Mediterranean chicken bowl",
            calories=l_cal,
            protein_g=32,
            carbs_g=42,
            fat_g=15,
            portion="150g chicken + quinoa + vegetables + tahini"
        ),
        MealItem(
            name="Salmon poke bowl",
            calories=l_cal,
            protein_g=30,
            carbs_g=45,
            fat_g=18,
            portion="120g salmon + rice + edamame + avocado"
        )
    ]
    
    dinner_options = [
        MealItem(
            name="Turkey meatballs with whole wheat pasta",
            calories=d_cal,
            protein_g=28,
            carbs_g=35,
            fat_g=12,
            portion="150g turkey + 80g pasta + marinara"
        ),
        MealItem(
            name="Grilled fish with roasted vegetables",
            calories=d_cal,
            protein_g=30,
            carbs_g=25,
            fat_g=15,
            portion="150g white fish + mixed vegetables"
        )
    ]
    
    for i, day in enumerate(days):
        total = b_cal + ms_cal + l_cal + as_cal + d_cal
        meals.append(DayMeals(
            day=day,
            breakfast=breakfast_options[i % len(breakfast_options)],
            morning_snack=snack_options[i % len(snack_options)],
            lunch=lunch_options[i % len(lunch_options)],
            afternoon_snack=snack_options[(i+1) % len(snack_options)],
            dinner=dinner_options[i % len(dinner_options)],
            total_calories=total
        ))
    
    return meals


# ============================================================================
# Helper Function
# ============================================================================

def _profile_to_request(profile: dict, activity_level: str = "moderate") -> CalorieRequest:
    """Convert Supabase profile to CalorieRequest"""
    gender = profile.get("gender") or "male"
    if gender not in ("male", "female"):
        gender = "male"
    
    goal = profile.get("fitness_goal") or "maintain"
    if goal not in ("lose_weight", "build_muscle", "maintain"):
        goal = "maintain"
    
    return CalorieRequest(
        gender=gender,
        age=int(profile.get("age") or 25),
        height=float(profile.get("height") or 170),
        weight=float(profile.get("weight") or 70),
        activity_level=activity_level,
        goal=goal,
    )


# ============================================================================
# API Endpoints
# ============================================================================

@router.post("/nutrition/calculate", response_model=CalorieResponse)
async def calculate_nutrition(
    data: CalorieRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Calculate BMR, TDEE, target calories, and macros (authenticated).
    
    Requires authentication.
    """
    try:
        return calculate_calories(data)
    except Exception as e:
        logger.error(f"Calorie calculation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nutrition/calculate-public", response_model=CalorieResponse)
async def calculate_nutrition_public(data: CalorieRequest):
    """
    Calculate BMR, TDEE, target calories, and macros (public).
    
    No authentication required.
    """
    try:
        return calculate_calories(data)
    except Exception as e:
        logger.error(f"Calorie calculation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/nutrition/plan", response_model=NutritionPlanResponse)
async def generate_plan(
    data: CalorieRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Generate 7-day meal plan (authenticated).
    
    Requires authentication.
    """
    try:
        calorie_result = calculate_calories(data)
        plan = generate_nutrition_plan(
            calorie_result.target_calories,
            data.goal,
            data.gender
        )
        return plan
    except Exception as e:
        logger.error(f"Meal plan generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nutrition/plan-public", response_model=NutritionPlanResponse)
async def generate_plan_public(data: CalorieRequest):
    """
    Generate 7-day meal plan (public).
    
    No authentication required.
    """
    try:
        calorie_result = calculate_calories(data)
        plan = generate_nutrition_plan(
            calorie_result.target_calories,
            data.goal,
            data.gender
        )
        return plan
    except Exception as e:
        logger.error(f"Meal plan generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nutrition/from-profile", response_model=AutoCalorieResponse)
async def calculate_from_profile(
    activity_level: str = Query("moderate", regex="^(sedentary|light|moderate|active|very_active)$"),
    current_user: dict = Depends(get_current_user)
):
    """
    Calculate calories automatically from user profile.
    
    Requires authentication. Fetches profile data and calculates nutrition needs.
    """
    try:
        user_id = current_user["id"]
        
        profile = get_profile(user_id)
        if not profile:
            raise HTTPException(
                status_code=404,
                detail="Profile not found. Please complete onboarding first."
            )
        
        # Convert profile to request
        calc_request = _profile_to_request(profile, activity_level)
        
        # Calculate calories
        calorie_result = calculate_calories(calc_request)
        
        # Build profile data response
        profile_data = ProfileData(
            gender=profile.get("gender") or "male",
            age=profile.get("age") or 25,
            height=profile.get("height") or 170,
            weight=profile.get("weight") or 70,
            fitness_goal=profile.get("fitness_goal") or "maintain",
            full_name=profile.get("full_name"),
            training_days_per_week=profile.get("training_days_per_week"),
            preferred_workout_duration=profile.get("preferred_workout_duration")
        )
        
        return AutoCalorieResponse(
            profile=profile_data,
            calories=calorie_result
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Profile-based calculation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/nutrition/plan-from-profile", response_model=AutoPlanResponse)
async def generate_plan_from_profile(
    activity_level: str = Query("moderate", regex="^(sedentary|light|moderate|active|very_active)$"),
    current_user: dict = Depends(get_current_user)
):
    """
    Generate complete meal plan from user profile.
    
    Requires authentication. Fetches profile, calculates calories, and generates meal plan.
    """
    try:
        user_id = current_user["id"]
        
        profile = get_profile(user_id)
        if not profile:
            raise HTTPException(
                status_code=404,
                detail="Profile not found. Please complete onboarding first."
            )
        
        # Convert profile to request
        calc_request = _profile_to_request(profile, activity_level)
        
        # Calculate calories
        calorie_result = calculate_calories(calc_request)
        
        # Generate meal plan
        meal_plan = generate_nutrition_plan(
            calorie_result.target_calories,
            calc_request.goal,
            calc_request.gender
        )
        
        # Build profile data response
        profile_data = ProfileData(
            gender=profile.get("gender") or "male",
            age=profile.get("age") or 25,
            height=profile.get("height") or 170,
            weight=profile.get("weight") or 70,
            fitness_goal=profile.get("fitness_goal") or "maintain",
            full_name=profile.get("full_name"),
            training_days_per_week=profile.get("training_days_per_week"),
            preferred_workout_duration=profile.get("preferred_workout_duration")
        )
        
        return AutoPlanResponse(
            profile=profile_data,
            calories=calorie_result,
            plan=meal_plan
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Profile-based plan generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
