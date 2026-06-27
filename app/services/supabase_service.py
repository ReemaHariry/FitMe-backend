"""
Supabase Service Module

This is the single source of truth for Supabase client initialization.
All database and auth operations go through this service.

Why centralize this?
- Single client instance prevents connection issues
- Easy to mock for testing
- Consistent error handling
- One place to update if Supabase config changes
"""

from supabase import create_client, Client
from typing import Optional, Dict, Any
from datetime import datetime
import logging
from app.config import settings

# Configure logger
logger = logging.getLogger(__name__)


# ============================================================================
# SUPABASE CLIENT INITIALIZATION
# ============================================================================

# Global client instance (initialized once)
_supabase_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """
    Get or create the Supabase client instance.
    
    This uses the SERVICE ROLE KEY which bypasses Row Level Security.
    Use this for server-side operations only - never expose this key to frontend!
    
    Returns:
        Client: Initialized Supabase client
        
    Raises:
        ValueError: If Supabase credentials are not configured
    """
    global _supabase_client
    
    if _supabase_client is None:
        if not settings.supabase_url or not settings.supabase_service_key:
            raise ValueError(
                "Supabase credentials not configured. "
                "Please set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env file"
            )
        
        # FIXED: Log to verify we're using the service role key
        logger.info(f"Initializing Supabase client with URL: {settings.supabase_url}")
        logger.info(f"Using service_role key: {settings.supabase_service_key[:20]}...")
        
        # Create client with positional arguments (compatible with all versions)
        # IMPORTANT: The service_role key should bypass RLS automatically
        _supabase_client = create_client(
            settings.supabase_url,
            settings.supabase_service_key
        )
        
        logger.info("✅ Supabase client initialized successfully")
    
    return _supabase_client


# ============================================================================
# PROFILE MANAGEMENT FUNCTIONS
# ============================================================================

def save_profile(user_id: str, profile_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Save or update user profile in the profiles table.
    
    Uses upsert pattern: if profile exists, update it; if not, create it.
    
    Args:
        user_id: UUID of the user
        profile_data: Dictionary containing profile fields
        
    Returns:
        Dict containing the saved profile data
        
    Raises:
        Exception: If database operation fails
    """
    supabase = get_supabase_client()
    
    # Prepare data for database
    db_data = {
        "user_id": user_id,
        "full_name": profile_data.get("full_name"),
        "gender": profile_data.get("gender"),
        "age": profile_data.get("age"),
        "height": profile_data.get("height"),
        "weight": profile_data.get("weight"),
        "fitness_goal": profile_data.get("fitness_goal"),
        "training_days_per_week": profile_data.get("training_days_per_week"),
        "preferred_workout_duration": profile_data.get("preferred_workout_duration"),
        "onboarding_complete": profile_data.get("onboarding_complete", True),
        "updated_at": datetime.now().isoformat(),  # ADDED: Track update time
    }
    
    # Upsert: insert or update if exists
    # on_conflict tells Supabase which field to check for conflicts
    result = supabase.table("profiles").upsert(
        db_data,
        on_conflict="user_id"
    ).execute()
    
    if result.data:
        return result.data[0]
    else:
        raise Exception("Failed to save profile")


# ADDED: New function for partial profile updates
def update_profile(user_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update specific fields in user profile (PATCH semantics).
    
    Only updates the fields provided in update_data.
    Always sets updated_at timestamp.
    
    Args:
        user_id: UUID of the user
        update_data: Dictionary with fields to update
        
    Returns:
        Dict containing the updated profile data
        
    Raises:
        Exception: If update fails
    """
    supabase = get_supabase_client()
    
    # Add updated_at timestamp
    update_data["updated_at"] = datetime.now().isoformat()
    
    # Update only provided fields
    result = supabase.table("profiles").update(
        update_data
    ).eq("user_id", user_id).execute()
    
    if result.data and len(result.data) > 0:
        return result.data[0]
    else:
        raise Exception("Failed to update profile")


def get_profile(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch user profile from the profiles table.
    
    Args:
        user_id: UUID of the user
        
    Returns:
        Dict containing profile data, or None if not found
    """
    supabase = get_supabase_client()
    
    result = supabase.table("profiles").select("*").eq("user_id", user_id).execute()
    
    if result.data and len(result.data) > 0:
        return result.data[0]
    return None


def update_onboarding_status(user_id: str, complete: bool) -> Dict[str, Any]:
    """
    Update only the onboarding_complete flag for a user.
    
    Args:
        user_id: UUID of the user
        complete: True if onboarding is complete, False otherwise
        
    Returns:
        Dict containing updated data
    """
    supabase = get_supabase_client()
    
    result = supabase.table("profiles").update(
        {"onboarding_complete": complete, "updated_at": datetime.now().isoformat()}
    ).eq("user_id", user_id).execute()
    
    if result.data and len(result.data) > 0:
        return result.data[0]
    else:
        raise Exception("Failed to update onboarding status")


# ============================================================================
# ACCOUNT MANAGEMENT FUNCTIONS
# ============================================================================

def delete_user_account(user_id: str) -> bool:
    """
    Permanently delete a user account from Supabase Auth.
    Because of Supabase's cascade delete rules, this will automatically
    delete their profile, sessions, weight logs, and progress photos.
    
    Args:
        user_id: UUID of the user
        
    Returns:
        True if successful
        
    Raises:
        Exception: If deletion fails
    """
    try:
        supabase = get_supabase_client()
        # Requires the service_role key to be used (which we initialize in get_supabase_client)
        response = supabase.auth.admin.delete_user(user_id)
        return True
    except Exception as e:
        logger.error(f"Failed to delete user account {user_id}: {e}")
        raise Exception(f"Failed to delete account: {str(e)}")


# ============================================================================
# AUTHENTICATION HELPER FUNCTIONS
# ============================================================================

def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify a JWT token and return the user data.
    
    This calls Supabase's get_user() which:
    - Validates the token signature
    - Checks if token is expired
    - Returns the user object if valid
    
    Args:
        token: JWT access token from Authorization header
        
    Returns:
        Dict containing user data if valid, None if invalid
    """
    try:
        supabase = get_supabase_client()
        response = supabase.auth.get_user(token)
        
        if response and response.user:
            return {
                "id": response.user.id,
                "email": response.user.email,
                "created_at": response.user.created_at.isoformat() if response.user.created_at else None,  # ADDED
                "user_metadata": response.user.user_metadata or {}
            }
        return None
    except Exception as e:
        print(f"Token verification failed: {str(e)}")
        return None


# ============================================================================
# REPORTS MANAGEMENT FUNCTIONS
# ============================================================================

def get_user_reports(user_id: str) -> list:
    """
    Get all reports for a user with session details.
    
    This performs a JOIN between reports and exercise_sessions tables
    to get complete information for each report.
    
    Args:
        user_id: UUID of the user
        
    Returns:
        List of report summary dicts, ordered by generated_at DESC
    """
    try:
        supabase = get_supabase_client()
        
        # First, get all reports for the user
        reports_result = supabase.table("reports").select(
            "id, session_id, exercise_type, form_score, performance_rating, total_mistakes, generated_at"
        ).eq("user_id", user_id).order("generated_at", desc=True).execute()
        
        # Then, for each report, get the session details
        reports = []
        for report in reports_result.data:
            session_id = report.get("session_id")
            
            # Fetch session details
            session_result = supabase.table("exercise_sessions").select(
                "session_name, duration_seconds"
            ).eq("id", session_id).execute()
            
            session = session_result.data[0] if session_result.data else {}
            
            reports.append({
                "id": report["id"],
                "session_id": report["session_id"],
                "exercise_type": report["exercise_type"],
                "form_score": report["form_score"],
                "performance_rating": report["performance_rating"],
                "total_mistakes": report["total_mistakes"],
                "duration_seconds": session.get("duration_seconds", 0),
                "session_name": session.get("session_name", "Unknown Session"),
                "generated_at": report["generated_at"],
                "created_at": report["generated_at"]  # Use generated_at for created_at
            })
        
        return reports
        
    except Exception as e:
        print(f"ERROR in get_user_reports: {str(e)}")
        print(f"ERROR type: {type(e)}")
        import traceback
        traceback.print_exc()
        raise


def get_report_by_id(report_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a single report by ID with full details.
    
    SECURITY CHECK: Verifies the report belongs to the requesting user.
    This prevents users from accessing other users' reports.
    
    Args:
        report_id: UUID of the report
        user_id: UUID of the user (for security check)
        
    Returns:
        Dict containing full report data with nested session info, or None if not found
        
    Raises:
        Exception: If report doesn't belong to user (security violation)
    """
    supabase = get_supabase_client()
    
    # Fetch report with session details
    result = supabase.table("reports").select(
        """
        id,
        session_id,
        full_report,
        exercise_type,
        form_score,
        performance_rating,
        total_mistakes,
        generated_at,
        user_id,
        exercise_sessions!inner(
            session_name,
            duration_seconds,
            started_at,
            ended_at
        )
        """
    ).eq("id", report_id).execute()
    
    if not result.data or len(result.data) == 0:
        return None
    
    report = result.data[0]
    
    # SECURITY CHECK: Verify ownership
    if report["user_id"] != user_id:
        raise Exception("Unauthorized: Report does not belong to this user")
    
    # Extract session data
    session = report.get("exercise_sessions", {})
    
    # Return structured response
    return {
        "id": report["id"],
        "session_id": report["session_id"],
        "full_report": report["full_report"],
        "exercise_type": report["exercise_type"],
        "form_score": report["form_score"],
        "performance_rating": report["performance_rating"],
        "total_mistakes": report["total_mistakes"],
        "generated_at": report["generated_at"],
        "session": {
            "session_name": session.get("session_name", "Unknown Session"),
            "duration_seconds": session.get("duration_seconds", 0),
            "started_at": session.get("started_at"),
            "ended_at": session.get("ended_at")
        }
    }


def create_session(
    user_id: str,
    exercise_type: str,
    session_name: str,
    duration_seconds: float,
    form_score: int,
    performance_rating: str,
    total_mistakes: int,
    total_frames_processed: int,
    started_at: str,
    ended_at: str
) -> str:
    """
    Create a new exercise session record.
    
    This will be called by the AI pipeline when a workout session completes.
    
    Args:
        user_id: UUID of the user
        exercise_type: Type of exercise (e.g., "squat", "pushup")
        session_name: Human-readable session name
        duration_seconds: Total duration in seconds
        form_score: Overall form score (0-100)
        performance_rating: Rating (excellent/good/fair/needs_improvement)
        total_mistakes: Total number of mistakes detected
        total_frames_processed: Number of video frames analyzed
        started_at: ISO timestamp when session started
        ended_at: ISO timestamp when session ended
        
    Returns:
        str: UUID of the created session
    """
    supabase = get_supabase_client()
    
    session_data = {
        "user_id": user_id,
        "exercise_type": exercise_type,
        "session_name": session_name,
        "duration_seconds": duration_seconds,
        "form_score": form_score,
        "performance_rating": performance_rating,
        "total_mistakes": total_mistakes,
        "total_frames_processed": total_frames_processed,
        "status": "completed",
        "started_at": started_at,
        "ended_at": ended_at
    }
    
    result = supabase.table("exercise_sessions").insert(session_data).execute()
    
    if result.data and len(result.data) > 0:
        return result.data[0]["id"]
    else:
        raise Exception("Failed to create session")


def create_report(
    session_id: str,
    user_id: str,
    report: Dict[str, Any],
    exercise_type: str,
    form_score: int,
    performance_rating: str,
    total_mistakes: int
) -> str:
    """
    Create a new report record.
    
    This stores the complete ReportGenerator output in the full_report JSONB field.
    
    Args:
        session_id: UUID of the exercise session
        user_id: UUID of the user
        report: Complete report dict from ReportGenerator.generate_report()
        exercise_type: Type of exercise
        form_score: Overall form score (0-100)
        performance_rating: Rating (excellent/good/fair/needs_improvement)
        total_mistakes: Total number of mistakes
        
    Returns:
        str: UUID of the created report
    """
    supabase = get_supabase_client()
    
    report_data = {
        "session_id": session_id,
        "user_id": user_id,
        "full_report": report,  # JSONB field - stores entire report structure
        "exercise_type": exercise_type,
        "form_score": form_score,
        "performance_rating": performance_rating,
        "total_mistakes": total_mistakes
    }
    
    result = supabase.table("reports").insert(report_data).execute()
    
    if result.data and len(result.data) > 0:
        return result.data[0]["id"]
    else:
        raise Exception("Failed to create report")


def get_user_stats(user_id: str) -> Dict[str, Any]:
    """
    Get aggregate statistics for a user across all sessions.
    
    This calculates:
    - Total number of completed sessions
    - Total minutes trained
    - Average form score across all sessions
    - Most practiced exercise type
    
    Args:
        user_id: UUID of the user
        
    Returns:
        Dict containing aggregate stats
    """
    supabase = get_supabase_client()
    
    # Fetch all completed sessions for the user
    result = supabase.table("exercise_sessions").select(
        "duration_seconds, form_score, exercise_type"
    ).eq("user_id", user_id).eq("status", "completed").execute()
    
    sessions = result.data
    
    if not sessions or len(sessions) == 0:
        return {
            "total_sessions": 0,
            "total_minutes": 0,
            "average_form_score": None,
            "best_exercise": None
        }
    
    # Calculate total sessions
    total_sessions = len(sessions)
    
    # Calculate total minutes
    total_seconds = sum(s.get("duration_seconds", 0) for s in sessions)
    total_minutes = round(total_seconds / 60, 1)
    
    # Calculate average form score (only for sessions with scores)
    scores = [s["form_score"] for s in sessions if s.get("form_score") is not None]
    average_form_score = round(sum(scores) / len(scores), 1) if scores else None
    
    # Find most common exercise type
    exercise_counts = {}
    for session in sessions:
        ex_type = session.get("exercise_type")
        if ex_type:
            exercise_counts[ex_type] = exercise_counts.get(ex_type, 0) + 1
    
    best_exercise = max(exercise_counts, key=exercise_counts.get) if exercise_counts else None
    
    return {
        "total_sessions": total_sessions,
        "total_minutes": total_minutes,
        "average_form_score": average_form_score,
        "best_exercise": best_exercise
    }


# ============================================================================
# VIDEO STORAGE FUNCTIONS (Feature 6)
# ============================================================================

async def upload_video_to_storage(file_bytes: bytes, filename: str, user_id: str) -> str:
    """
    Upload video file to Supabase Storage (PRIVATE bucket).
    
    Files are organized by user_id to prevent collisions and enable
    user-specific access policies.
    
    Args:
        file_bytes: Raw bytes of the video file
        filename: Original filename with extension
        user_id: UUID string for namespacing
        
    Returns:
        str: Storage path (NOT a URL - path within the bucket)
        
    Raises:
        HTTPException: If upload fails
    """
    from fastapi import HTTPException
    from datetime import datetime
    
    supabase = get_supabase_client()
    
    # Generate unique storage path
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_filename = f"{user_id}/{timestamp}_{filename}"
    
    try:
        # Upload to private bucket
        # Note: file_options values must be strings, not booleans
        supabase.storage.from_("workout-videos").upload(
            path=safe_filename,
            file=file_bytes,
            file_options={"content-type": "video/mp4"}
        )
        
        logger.info(f"Video uploaded to storage: {safe_filename}")
        
        # Return the storage path (not a URL)
        # We'll generate signed URLs when needed for viewing
        return safe_filename
        
    except Exception as e:
        logger.error(f"Failed to upload video: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to upload video to storage: {str(e)}")


async def get_video_signed_url(storage_path: str, expires_in: int = 3600) -> str:
    """
    Generate a signed URL for accessing a private video file.
    
    Signed URLs are temporary and secure - they expire after the specified time.
    
    Args:
        storage_path: Path to the file in storage (e.g., "user_id/timestamp_filename.mp4")
        expires_in: URL expiration time in seconds (default: 1 hour)
        
    Returns:
        str: Signed URL that can be used to access the video
    """
    supabase = get_supabase_client()
    
    try:
        # Generate signed URL
        result = supabase.storage.from_("workout-videos").create_signed_url(
            storage_path,
            expires_in
        )
        
        if result and "signedURL" in result:
            return result["signedURL"]
        else:
            logger.error(f"Failed to generate signed URL for {storage_path}")
            return ""
            
    except Exception as e:
        logger.error(f"Error generating signed URL: {str(e)}")
        return ""


async def create_session_record(
    user_id: str,
    exercise_type: str,
    session_name: str,
    video_storage_path: str
) -> str:
    """
    Create a new exercise session record.
    Status will be set by database default or updated after analysis.
    
    Args:
        user_id: UUID of the user
        exercise_type: Type of exercise
        session_name: Human-readable session name
        video_storage_path: Path to video in storage (NOT a URL)
        
    Returns:
        str: UUID of the created session
    """
    supabase = get_supabase_client()
    
    session_data = {
        "user_id": user_id,
        "exercise_type": exercise_type,
        "session_name": session_name,
        "video_url": video_storage_path,  # Store path, not URL
        "started_at": datetime.now().isoformat()
        # Don't set status - let database use default or we'll update after analysis
    }
    
    result = supabase.table("exercise_sessions").insert(session_data).execute()
    
    if result.data and len(result.data) > 0:
        return result.data[0]["id"]
    else:
        raise Exception("Failed to create session record")


async def update_session_after_analysis(
    session_id: str,
    form_score: int,
    performance_rating: str,
    total_mistakes: int,
    total_frames_processed: int,
    duration_seconds: float,
    exercise_detected: str,
    status: str = "completed"
) -> None:
    """
    Update session record with analysis results.
    
    FIXED: Ensure duration_seconds is properly saved as float
    
    Args:
        session_id: UUID of the session
        form_score: Calculated form score (0-100)
        performance_rating: Rating from report
        total_mistakes: Total mistakes detected
        total_frames_processed: Number of frames analyzed
        duration_seconds: Session duration (MUST be > 0)
        exercise_detected: Detected exercise type
        status: Final status (default: "completed")
    """
    supabase = get_supabase_client()
    
    # FIXED: Explicitly convert to float and log the value
    duration_float = float(duration_seconds)
    logger.info(f"Updating session {session_id} with duration={duration_float}s")
    
    update_data = {
        "form_score": form_score,
        "performance_rating": performance_rating,
        "total_mistakes": total_mistakes,
        "total_frames_processed": total_frames_processed,
        "duration_seconds": duration_float,  # FIXED: Ensure it's a float
        "exercise_type": exercise_detected,
        "status": status,
        "ended_at": datetime.now().isoformat()
    }
    
    try:
        result = supabase.table("exercise_sessions").update(update_data).eq("id", session_id).execute()
        logger.info(f"Session update result: {result.data}")
    except Exception as e:
        logger.error(f"Failed to update session {session_id}: {str(e)}")
        # Don't raise - report is already saved, session update failing is not critical


async def save_report_record(
    session_id: str,
    user_id: str,
    report: dict,
    exercise_type: str,
    form_score: int,
    performance_rating: str,
    total_mistakes: int
) -> str:
    """
    Save report to database.
    
    Args:
        session_id: UUID of the session
        user_id: UUID of the user
        report: Complete report dict from ReportGenerator
        exercise_type: Type of exercise
        form_score: Form score (0-100)
        performance_rating: Performance rating
        total_mistakes: Total mistakes
        
    Returns:
        str: UUID of the created report
        
    Raises:
        HTTPException: If save fails
    """
    from fastapi import HTTPException
    
    supabase = get_supabase_client()
    
    report_data = {
        "session_id": session_id,
        "user_id": user_id,
        "full_report": report,
        "exercise_type": exercise_type,
        "form_score": form_score,
        "performance_rating": performance_rating,
        "total_mistakes": total_mistakes
    }
    
    try:
        result = supabase.table("reports").insert(report_data).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]["id"]
        else:
            raise Exception("No data returned from insert")
            
    except Exception as e:
        logger.error(f"Failed to save report: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to save report")


async def get_session_status(session_id: str, user_id: str) -> Optional[dict]:
    """
    Get session status for polling.
    
    Args:
        session_id: UUID of the session
        user_id: UUID of the user (for security)
        
    Returns:
        Dict with session info or None if not found
    """
    supabase = get_supabase_client()
    
    result = supabase.table("exercise_sessions").select(
        "id, status, exercise_type, session_name, created_at"
    ).eq("id", session_id).eq("user_id", user_id).execute()
    
    if result.data and len(result.data) > 0:
        return result.data[0]
    return None


# ============================================================================
# PROGRESS PHOTOS FUNCTIONS
# ============================================================================

def get_progress_photos(user_id: str) -> list:
    """
    Get all progress photos for a user with FRESH signed URLs.
    
    FIXED: Regenerates signed URLs on every fetch to ensure they're valid.
    Returns photos ordered by taken_at DESC (newest first).
    
    Args:
        user_id: UUID of the user
        
    Returns:
        List of progress photo dicts with fresh signed URLs
    """
    supabase = get_supabase_client()
    
    # Fetch photos ordered by taken_at DESC, then created_at DESC
    result = supabase.table("progress_photos").select(
        "id, user_id, photo_url, storage_path, photo_type, taken_at, created_at"
    ).eq("user_id", user_id).order("taken_at", desc=True).order("created_at", desc=True).execute()
    
    photos = result.data or []
    
    # FIXED: Regenerate fresh signed URLs
    photos = regenerate_photo_signed_urls(photos)
    
    return photos


def save_progress_photo(
    user_id: str,
    photo_url: str,
    storage_path: str,
    photo_type: str,
    taken_at: str
) -> dict:
    """
    Save a progress photo record to the database.
    
    Args:
        user_id: UUID of the user
        photo_url: Signed URL to access the photo
        storage_path: Path in storage bucket
        photo_type: 'front', 'side', or 'back'
        taken_at: Date when photo was taken (YYYY-MM-DD)
        
    Returns:
        Dict containing the created photo record
    """
    supabase = get_supabase_client()
    
    photo_data = {
        "user_id": user_id,
        "photo_url": photo_url,
        "storage_path": storage_path,
        "photo_type": photo_type,
        "taken_at": taken_at
    }
    
    result = supabase.table("progress_photos").insert(photo_data).execute()
    
    if result.data and len(result.data) > 0:
        return result.data[0]
    else:
        raise Exception("Failed to save progress photo")


def delete_progress_photo(photo_id: str, user_id: str) -> None:
    """
    Delete a progress photo from both storage and database.
    
    Security: Verifies the photo belongs to the user before deleting.
    
    Args:
        photo_id: UUID of the photo
        user_id: UUID of the user (for security check)
        
    Raises:
        Exception: If photo not found or doesn't belong to user
    """
    supabase = get_supabase_client()
    
    # First, get the photo to verify ownership and get storage_path
    photo_result = supabase.table("progress_photos").select(
        "storage_path"
    ).eq("id", photo_id).eq("user_id", user_id).execute()
    
    if not photo_result.data or len(photo_result.data) == 0:
        raise Exception("Photo not found or unauthorized")
    
    storage_path = photo_result.data[0]["storage_path"]
    
    # Delete from storage
    try:
        supabase.storage.from_("progress-photos").remove([storage_path])
        logger.info(f"Deleted photo from storage: {storage_path}")
    except Exception as e:
        logger.error(f"Failed to delete from storage: {str(e)}")
        # Continue with database deletion even if storage deletion fails
    
    # Delete from database
    supabase.table("progress_photos").delete().eq("id", photo_id).eq("user_id", user_id).execute()
    logger.info(f"Deleted photo record: {photo_id}")


def upload_progress_photo_to_storage(
    file_bytes: bytes,
    filename: str,
    user_id: str,
    photo_type: str
) -> tuple[str, str]:
    """
    Upload a progress photo to Supabase Storage (PRIVATE bucket).
    
    Files are organized by user_id and photo_type for easy management.
    FIXED: Generate fresh signed URL with 1 year expiration.
    
    Args:
        file_bytes: Raw bytes of the image file
        filename: Original filename with extension
        user_id: UUID string for namespacing
        photo_type: 'front', 'side', or 'back'
        
    Returns:
        tuple: (signed_url, storage_path)
        - signed_url: Temporary URL to access the photo (expires in 1 year)
        - storage_path: Path in storage bucket
        
    Raises:
        Exception: If upload fails
    """
    supabase = get_supabase_client()
    
    # Generate unique storage path
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Path format: user_id/photo_type_timestamp_filename.jpg
    storage_path = f"{user_id}/{photo_type}_{timestamp}_{filename}"
    
    try:
        # Upload to private bucket
        supabase.storage.from_("progress-photos").upload(
            path=storage_path,
            file=file_bytes,
            file_options={
                "content-type": "image/jpeg",
                "upsert": "true"  # Replace if exists
            }
        )
        
        logger.info(f"Progress photo uploaded to storage: {storage_path}")
        
        # FIXED: Generate signed URL (expires in 1 year = 365 days)
        signed_url_response = supabase.storage.from_("progress-photos").create_signed_url(
            storage_path,
            3600 * 24 * 365  # 1 year in seconds
        )
        
        if signed_url_response and "signedURL" in signed_url_response:
            signed_url = signed_url_response["signedURL"]
        else:
            raise Exception("Failed to generate signed URL")
        
        return signed_url, storage_path
        
    except Exception as e:
        logger.error(f"Failed to upload progress photo: {str(e)}")
        raise Exception(f"Failed to upload progress photo: {str(e)}")


# ADDED: Function to regenerate signed URLs for existing photos
def regenerate_photo_signed_urls(photos: list) -> list:
    """
    Regenerate signed URLs for a list of photos.
    
    This should be called when fetching progress photos to ensure
    URLs are fresh and valid.
    
    Args:
        photos: List of photo dicts with storage_path field
        
    Returns:
        List of photo dicts with updated photo_url (signed URL)
    """
    supabase = get_supabase_client()
    
    for photo in photos:
        try:
            storage_path = photo.get("storage_path")
            if storage_path:
                # Generate fresh signed URL
                signed_url_response = supabase.storage.from_("progress-photos").create_signed_url(
                    storage_path,
                    3600 * 24 * 365  # 1 year expiration
                )
                
                if signed_url_response and "signedURL" in signed_url_response:
                    photo["photo_url"] = signed_url_response["signedURL"]
                else:
                    logger.warning(f"Failed to generate signed URL for {storage_path}")
        except Exception as e:
            logger.error(f"Error regenerating signed URL: {str(e)}")
            # Keep old URL if regeneration fails
            
    return photos


# ============================================================================
# WEIGHT TRACKING FUNCTIONS
# ============================================================================

def get_weight_logs(user_id: str, limit: int = 10) -> list:
    """
    Get weight log history for a user.
    
    Returns logs ordered by logged_at ASC (oldest first) for charting.
    
    Args:
        user_id: UUID of the user
        limit: Maximum number of logs to return (default 10, max 30)
        
    Returns:
        List of weight log dicts ordered by date
    """
    supabase = get_supabase_client()
    
    # Cap limit at 30
    limit = min(limit, 30)
    
    result = supabase.table("weight_logs").select(
        "id, weight_kg, logged_at, note, created_at"
    ).eq("user_id", user_id).order("logged_at", desc=False).limit(limit).execute()
    
    return result.data or []


def log_weight(user_id: str, weight_kg: float, note: str = None) -> dict:
    """
    Log a new weight entry for the user.
    
    Args:
        user_id: UUID of the user
        weight_kg: Weight in kilograms (must be between 10 and 500)
        note: Optional note about the weigh-in
        
    Returns:
        Dict containing the created log entry
        
    Raises:
        ValueError: If weight_kg is out of valid range
    """
    if weight_kg < 10 or weight_kg > 500:
        raise ValueError("Weight must be between 10 and 500 kg")
    
    supabase = get_supabase_client()
    from datetime import date
    
    log_data = {
        "user_id": user_id,
        "weight_kg": weight_kg,
        "logged_at": date.today().isoformat(),
        "note": note
    }
    
    result = supabase.table("weight_logs").insert(log_data).execute()
    
    if result.data and len(result.data) > 0:
        return result.data[0]
    else:
        raise Exception("Failed to log weight")


def delete_weight_log(log_id: str, user_id: str) -> None:
    """
    Delete a weight log entry.
    
    Security: Verifies the log belongs to the user before deleting.
    
    Args:
        log_id: UUID of the log entry
        user_id: UUID of the user (for security check)
        
    Raises:
        Exception: If log not found or doesn't belong to user
    """
    supabase = get_supabase_client()
    
    # Delete with user_id check for security
    result = supabase.table("weight_logs").delete().eq(
        "id", log_id
    ).eq("user_id", user_id).execute()
    
    if not result.data or len(result.data) == 0:
        raise Exception("Weight log not found or unauthorized")
    
    logger.info(f"Deleted weight log: {log_id}")

