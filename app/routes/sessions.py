"""
Sessions Routes

Handles live training session lifecycle management.
POST /sessions/start       — creates session in memory AND in database
POST /sessions/{id}/end    — ends session, generates report, saves to DB
GET  /sessions/recent      — returns the last N completed sessions (dashboard)
"""

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
import logging

from app.services import session_service
from app.services.supabase_service import get_supabase_client
from app.reports.report_generator import ReportGenerator
from app.ai.pose_utils import calculate_form_score
from app.routes.users import get_current_user

logger = logging.getLogger(__name__)

# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class StartSessionRequest(BaseModel):
    """Request body for starting a live session"""
    exercise_name: str
    session_name: Optional[str] = None


class StartSessionResponse(BaseModel):
    """Response from starting a live session"""
    session_id: str
    message: str
    websocket_url: str


class EndSessionRequest(BaseModel):
    """Request body for ending a live session"""
    exercise_name: str
    session_name: Optional[str] = None


class EndSessionResponse(BaseModel):
    """Response from ending a live session"""
    session_id: str
    report_id: str
    message: str
    report: Dict[str, Any]
    metrics: Dict[str, Any]


# ============================================================================
# ROUTER SETUP
# ============================================================================

router = APIRouter(
    # prefix="/sessions",  # ← REMOVED: prefix is set in main.py
    tags=["Sessions"]
)


# ============================================================================
# ENDPOINT: POST /sessions/start
# ============================================================================

@router.post("/start", response_model=StartSessionResponse)
async def start_session(
    request: StartSessionRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Start a new live training session.
    
    Process:
    1. Validate exercise_name
    2. Generate session_name if None
    3. Create session in memory (session_service)
    4. Insert into exercise_sessions table with status='processing'
    5. Return session_id and websocket_url
    
    The session_id returned here is used by React to:
    - Open the WebSocket connection
    - Call POST /sessions/{id}/end
    
    Args:
        request: StartSessionRequest with exercise_name and optional session_name
        current_user: Current authenticated user from token
        
    Returns:
        StartSessionResponse with session_id and websocket_url
        
    Raises:
        400: Invalid exercise_name
        500: Failed to create session
    """
    try:
        user_id = current_user["id"]
        
        # Validate exercise_name (allow "unknown" for AI auto-detection)
        valid_exercises = ["squat", "push_up", "sit_up", "pushup", "situp", "unknown"]
        exercise_normalized = request.exercise_name.lower().replace("-", "_").replace(" ", "_")
        
        if exercise_normalized not in valid_exercises:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid exercise_name. Must be one of: {', '.join(valid_exercises)}"
            )
        
        # Generate session_name if None
        if not request.session_name:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            session_name = f"{request.exercise_name.replace('_', ' ').title()} Live Session - {timestamp}"
        else:
            session_name = request.session_name
        
        # Create session in memory
        session_id, tracker = session_service.create_live_session(
            user_id=user_id,
            session_name=session_name
        )
        
        # Insert into database with status='active' (live session in progress)
        supabase = get_supabase_client()
        
        session_data = {
            "id": session_id,  # Use the same UUID from memory
            "user_id": user_id,
            "exercise_type": request.exercise_name,
            "session_name": session_name,
            "video_url": None,  # NULL for live sessions
            "status": "active",  # FIXED: Changed back to 'active' (valid status value)
            "started_at": datetime.now().isoformat()
        }
        
        try:
            result = supabase.table("exercise_sessions").insert(session_data).execute()
            
            if not result.data:
                raise Exception("Failed to create session record in database")
        except Exception as db_error:
            logger.error(f"Database insert failed: {db_error}")
            # If RLS is blocking, try to provide more helpful error message
            if "row-level security" in str(db_error).lower():
                logger.error(
                    f"RLS Policy Error: The service role key should bypass RLS. "
                    f"Please check: 1) SUPABASE_SERVICE_KEY is set correctly in .env, "
                    f"2) You're using the service_role key (not anon key), "
                    f"3) RLS policies on exercise_sessions table"
                )
            raise
        
        logger.info(f"Live session started: {session_id} for user {user_id}")
        
        return StartSessionResponse(
            session_id=session_id,
            message="Session started successfully",
            websocket_url=f"/ws/live/{session_id}"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start session: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start session: {str(e)}"
        )


# ============================================================================
# ENDPOINT: POST /sessions/{session_id}/end
# ============================================================================

@router.post("/{session_id}/end", response_model=EndSessionResponse)
async def end_session(
    session_id: str,
    request: EndSessionRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    End a live training session and generate report.
    
    Process:
    1. Validate current_user
    2. Call session_service.end_live_session(session_id)
    3. Generate report with ReportGenerator
    4. Calculate form_score
    5. Save report to database
    6. Update exercise_sessions row with results
    7. Return complete report and metrics
    
    Args:
        session_id: UUID of the session (from URL path)
        request: EndSessionRequest with exercise_name and session_name
        current_user: Current authenticated user from token
        
    Returns:
        EndSessionResponse with full report and metrics
        
    Raises:
        404: Session not found or already ended
        500: Failed to generate or save report
    """
    try:
        user_id = current_user["id"]
        
        # End session in memory and get tracker
        tracker = session_service.end_live_session(session_id)
        
        if tracker is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or already ended"
            )
        
        # Generate report
        session_data = tracker.get_session_summary()
        report = ReportGenerator.generate_report(session_data)
        
        # Calculate form_score
        form_score = calculate_form_score(
            report,
            session_data["total_frames_processed"]
        )
        
        # Extract metrics
        performance_rating = report["overall_summary"]["performance_rating"]
        total_mistakes = report["statistics"]["total_mistakes"]
        duration_seconds = session_data["duration_seconds"]
        
        # Determine exercise name with proper fallback logic
        # Priority: detected > requested > "Unknown"
        detected_exercise = session_data.get("exercise_detected")
        requested_exercise = request.exercise_name if request.exercise_name and request.exercise_name.strip() and request.exercise_name.lower() != "unknown" else None
        
        exercise_detected = detected_exercise or requested_exercise or "Unknown"
        
        # Save report to database
        supabase = get_supabase_client()
        
        report_data = {
            "session_id": session_id,
            "user_id": user_id,
            "full_report": report,
            "exercise_type": exercise_detected,
            "form_score": form_score,
            "performance_rating": performance_rating,
            "total_mistakes": total_mistakes
        }
        
        report_result = supabase.table("reports").insert(report_data).execute()
        
        if not report_result.data:
            raise Exception("Failed to save report to database")
        
        report_id = report_result.data[0]["id"]
        
        # Update exercise_sessions row
        update_data = {
            "form_score": form_score,
            "performance_rating": performance_rating,
            "total_mistakes": total_mistakes,
            "total_frames_processed": session_data["total_frames_processed"],
            "duration_seconds": duration_seconds,
            "exercise_type": exercise_detected,
            "status": "completed",
            "ended_at": datetime.now().isoformat()
        }
        
        supabase.table("exercise_sessions").update(update_data).eq("id", session_id).execute()
        
        logger.info(f"Live session ended and report generated: {session_id} -> {report_id}")
        
        return EndSessionResponse(
            session_id=session_id,
            report_id=report_id,
            message="Session ended and report generated successfully",
            report=report,
            metrics={
                "form_score": form_score,
                "performance_rating": performance_rating,
                "total_mistakes": total_mistakes,
                "duration_seconds": duration_seconds,
                "total_frames_processed": session_data["total_frames_processed"],
                "exercise_detected": exercise_detected
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to end session {session_id}: {e}", exc_info=True)
        
        # Attempt to update session status to 'failed' in DB
        try:
            supabase = get_supabase_client()
            supabase.table("exercise_sessions").update({
                "status": "failed",
                "ended_at": datetime.now().isoformat()
            }).eq("id", session_id).execute()
        except Exception:
            pass
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to end session: {str(e)}"
        )


# ============================================================================
# ENDPOINT: GET /sessions/recent
# ============================================================================

@router.get("/recent")
async def get_recent_sessions(
    limit: int = 3,
    current_user: dict = Depends(get_current_user)
):
    """
    Returns the most recent completed sessions for the dashboard.

    Also fetches the report_id for each session (for deep-link navigation).
    Query param: limit (default 3, max 10)

    Returns:
        List of session dicts with id, session_name, exercise_type,
        duration_minutes, form_score, performance_rating, date_label, report_id
    """
    user_id = current_user["id"]

    # Guard against absurd limits
    if limit > 10:
        limit = 10

    try:
        supabase = get_supabase_client()

        # Fetch recent completed sessions
        sessions_result = supabase.table("exercise_sessions") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("status", "completed") \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()

        sessions = sessions_result.data or []

        if not sessions:
            return []

        # Fetch report IDs for these sessions in one query
        session_ids = [s["id"] for s in sessions]
        reports_result = supabase.table("reports") \
            .select("id, session_id") \
            .in_("session_id", session_ids) \
            .execute()

        report_map = {r["session_id"]: r["id"] for r in (reports_result.data or [])}

        # Format and return
        month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        result: List[dict] = []

        for s in sessions:
            created_at = s.get("created_at") or ""
            try:
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                date_label = f"{month_labels[dt.month - 1]} {dt.day}"
            except Exception:
                date_label = "Unknown"

            duration_seconds = s.get("duration_seconds") or 0
            duration_minutes = round(duration_seconds / 60)

            result.append({
                "id": s["id"],
                "session_name": (
                    s.get("session_name")
                    or f"{s.get('exercise_type', 'Session').replace('_', ' ').title()} Session"
                ),
                "exercise_type": s.get("exercise_type") or "unknown",
                "duration_seconds": duration_seconds,
                "duration_minutes": duration_minutes,
                "form_score": s.get("form_score"),
                "performance_rating": s.get("performance_rating") or "unknown",
                "total_mistakes": s.get("total_mistakes") or 0,
                "status": s.get("status"),
                "created_at": created_at,
                "date_label": date_label,
                "report_id": report_map.get(s["id"])
            })

        return result

    except Exception as e:
        logger.error(f"Recent sessions error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to load recent sessions")
