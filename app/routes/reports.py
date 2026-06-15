"""
Reports Routes

Handles workout reports and session analytics.
"""

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from app.services.supabase_service import (
    get_user_reports,
    get_report_by_id,
    create_report,
    create_session,
    get_user_stats
)
from app.routes.users import get_current_user


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class ReportSummary(BaseModel):
    """Summary of a report for list view"""
    id: str
    session_id: str
    exercise_type: str
    form_score: Optional[int]
    performance_rating: str
    total_mistakes: int
    duration_seconds: float
    session_name: str
    generated_at: str
    created_at: str


class SessionInfo(BaseModel):
    """Session details nested in report"""
    session_name: str
    duration_seconds: float
    started_at: Optional[str]
    ended_at: Optional[str]


class ReportDetailResponse(BaseModel):
    """Full report with all details"""
    id: str
    session_id: str
    full_report: Dict[str, Any]
    exercise_type: str
    form_score: int
    performance_rating: str
    total_mistakes: int
    generated_at: str
    session: SessionInfo


class UserStatsResponse(BaseModel):
    """Aggregate user statistics"""
    total_sessions: int
    total_minutes: float
    average_form_score: Optional[float]
    best_exercise: Optional[str]


class SeedTestDataResponse(BaseModel):
    """Response from seed endpoint"""
    message: str
    report_id: str
    session_id: str


# ============================================================================
# ROUTER SETUP
# ============================================================================

router = APIRouter(
    prefix="/reports",
    tags=["Reports"]
)


# ============================================================================
# ENDPOINT: GET /reports/health
# ============================================================================

@router.get("/health")
async def health_check():
    """
    Health check endpoint to verify Supabase connection.
    Does not require authentication.
    """
    try:
        from app.services.supabase_service import get_supabase_client
        supabase = get_supabase_client()
        
        # Try a simple query
        result = supabase.table("exercise_sessions").select("id").limit(1).execute()
        
        return {
            "status": "healthy",
            "supabase_connected": True,
            "message": "Database connection successful"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "supabase_connected": False,
            "error": str(e),
            "message": "Database connection failed"
        }


# ============================================================================
# ENDPOINT: GET /reports/stats
# ============================================================================
# IMPORTANT: This route MUST come BEFORE /reports/{report_id}
# 
# Why? FastAPI matches routes in order. If /reports/{report_id} comes first,
# FastAPI will try to match "stats" as a UUID parameter and fail with a
# validation error. By putting /reports/stats first, we explicitly handle
# the "stats" path before the generic {report_id} pattern.

@router.get("/stats", response_model=UserStatsResponse)
async def get_stats(current_user: dict = Depends(get_current_user)):
    """
    Get aggregate statistics for the current user.
    
    Returns:
    - total_sessions: Number of completed workout sessions
    - total_minutes: Total time spent training
    - average_form_score: Average form score across all sessions
    - best_exercise: Most frequently practiced exercise type
    
    Requires: Authorization header with valid Bearer token
    """
    try:
        user_id = current_user["id"]
        print(f"Fetching stats for user: {user_id}")
        stats = get_user_stats(user_id)
        print(f"Successfully fetched stats: {stats}")
        return UserStatsResponse(**stats)
    except Exception as e:
        print(f"ERROR in get_stats endpoint: {str(e)}")
        print(f"ERROR type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch statistics: {str(e)}"
        )


# ============================================================================
# ENDPOINT: GET /reports
# ============================================================================

@router.get("", response_model=List[ReportSummary])
async def get_reports(current_user: dict = Depends(get_current_user)):
    """
    Get all reports for the current user.
    
    Returns a list of report summaries with session details.
    The list is ordered by generated_at DESC (newest first).
    
    If the user has no reports yet, returns an empty list (NOT an error).
    
    Requires: Authorization header with valid Bearer token
    """
    try:
        user_id = current_user["id"]
        print(f"Fetching reports for user: {user_id}")
        reports = get_user_reports(user_id)
        print(f"Successfully fetched {len(reports)} reports")
        return [ReportSummary(**report) for report in reports]
    except Exception as e:
        print(f"ERROR in get_reports endpoint: {str(e)}")
        print(f"ERROR type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch reports: {str(e)}"
        )


# ============================================================================
# ENDPOINT: GET /reports/{report_id}
# ============================================================================

@router.get("/{report_id}", response_model=ReportDetailResponse)
async def get_report(
    report_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get a single report by ID with full details.
    
    Returns the complete report including:
    - Full report JSONB (from ReportGenerator)
    - Session metadata
    - All mistake details and corrections
    
    Security: Verifies the report belongs to the requesting user.
    
    Requires: Authorization header with valid Bearer token
    
    Raises:
    - 404: Report not found or doesn't belong to user
    """
    try:
        user_id = current_user["id"]
        report = get_report_by_id(report_id, user_id)
        
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report not found"
            )
        
        return ReportDetailResponse(**report)
        
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        if "Unauthorized" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report not found"
            )
        print(f"Report fetch error: {error_msg}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch report"
        )


# ============================================================================
# ENDPOINT: POST /reports/seed-test-data
# ============================================================================
# TODO: REMOVE THIS ENDPOINT BEFORE PRODUCTION
# This is for testing only - creates realistic fake data

@router.post("/seed-test-data", response_model=SeedTestDataResponse)
async def seed_test_data(current_user: dict = Depends(get_current_user)):
    """
    Create realistic test data for development and testing.
    
    This endpoint creates:
    1. A completed exercise session (squat workout)
    2. A full report with realistic mistakes and corrections
    
    The data structure matches EXACTLY what the real AI pipeline will produce.
    
    **WARNING: This is for testing only. Remove before production deployment.**
    
    Requires: Authorization header with valid Bearer token
    """
    try:
        user_id = current_user["id"]
        
        # Calculate timestamps
        now = datetime.utcnow()
        start_time = now - timedelta(minutes=5, seconds=32)
        
        # Create realistic full_report matching ReportGenerator output
        full_report = {
            "session_info": {
                "session_id": "test-session-" + now.strftime("%Y%m%d-%H%M%S"),
                "user_id": user_id,
                "session_name": "Test Session - Squat Practice",
                "start_time": start_time.isoformat() + "Z",
                "end_time": now.isoformat() + "Z",
                "duration_seconds": 332,
                "duration_formatted": "05:32",
                "exercise_detected": "squat",
                "total_frames_processed": 498
            },
            "overall_summary": {
                "performance_rating": "fair",
                "message": "Good effort! You completed the session with some areas needing attention. Focus on maintaining proper knee alignment and depth consistency.",
                "total_mistakes": 12,
                "unique_mistake_types": 3,
                "high_risk_warnings": 2,
                "duration_formatted": "05:32",
                "exercise_type": "squat"
            },
            "mistakes": [
                {
                    "mistake_type": "knees_past_toes",
                    "mistake_message": "Knees extending too far forward past toes",
                    "count": 7,
                    "first_seen_at": "00:45",
                    "last_seen_at": "04:12",
                    "timestamps": ["00:45", "01:23", "02:01", "02:34", "03:15", "03:48", "04:12"],
                    "severity": "high",
                    "correction_tip": "Keep your weight on your heels and push your hips back as you descend. Imagine sitting back into a chair.",
                    "warning": {
                        "level": "critical",
                        "message": "This mistake occurred 7 times - high frequency detected",
                        "injury_risk": "Repeated knee-over-toe positioning can strain the patellar tendon and increase risk of knee pain"
                    }
                },
                {
                    "mistake_type": "insufficient_depth",
                    "mistake_message": "Not reaching parallel depth in squat",
                    "count": 3,
                    "first_seen_at": "01:15",
                    "last_seen_at": "03:22",
                    "timestamps": ["01:15", "02:45", "03:22"],
                    "severity": "medium",
                    "correction_tip": "Descend until your hip crease is at or below knee level. Focus on mobility and gradually increase depth.",
                    "warning": None
                },
                {
                    "mistake_type": "forward_lean",
                    "mistake_message": "Excessive forward torso lean",
                    "count": 2,
                    "first_seen_at": "02:18",
                    "last_seen_at": "04:55",
                    "timestamps": ["02:18", "04:55"],
                    "severity": "medium",
                    "correction_tip": "Keep your chest up and core engaged. Maintain a more upright torso position throughout the movement.",
                    "warning": None
                }
            ],
            "statistics": {
                "total_mistakes": 12,
                "unique_mistake_types": 3,
                "most_common_mistake": "knees_past_toes",
                "high_frequency_mistakes": ["knees_past_toes"]
            },
            "generated_at": now.isoformat() + "Z"
        }
        
        # Create session
        session_id = create_session(
            user_id=user_id,
            exercise_type="squat",
            session_name="Test Session - Squat Practice",
            duration_seconds=332,
            form_score=64,
            performance_rating="fair",
            total_mistakes=12,
            total_frames_processed=498,
            started_at=start_time.isoformat() + "Z",
            ended_at=now.isoformat() + "Z"
        )
        
        # Create report
        report_id = create_report(
            session_id=session_id,
            user_id=user_id,
            report=full_report,
            exercise_type="squat",
            form_score=64,
            performance_rating="fair",
            total_mistakes=12
        )
        
        return SeedTestDataResponse(
            message="Test data created successfully",
            report_id=report_id,
            session_id=session_id
        )
        
    except Exception as e:
        print(f"Seed data error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create test data: {str(e)}"
        )
