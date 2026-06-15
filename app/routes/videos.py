"""
Video Upload and Analysis Routes
Handles video upload, AI analysis, and status checking.
"""
import os
import uuid
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, File, Form, UploadFile, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from app.services.supabase_service import (
    verify_token,
    upload_video_to_storage,
    create_session_record,
    update_session_after_analysis,
    save_report_record,
    get_session_status
)
from app.services.video_service import analyze_video

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class VideoUploadResponse(BaseModel):
    session_id: str
    report_id: str
    message: str
    report: dict
    video_storage_path: str
    metrics: dict


class AnalysisStatusResponse(BaseModel):
    session_id: str
    status: str
    message: str


# ============================================================================
# CONSTANTS
# ============================================================================

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024  # 500MB
TEMP_DIR = Path("/tmp/fitpose_videos")
TEMP_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# DEPENDENCY: GET CURRENT USER
# ============================================================================

async def get_current_user(request: Request):
    """
    Extract and verify the current user from the Authorization header.
    
    This is a dependency that can be injected into route handlers.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    
    token = auth_header.split(" ")[1]
    user_data = verify_token(token)
    
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    return user_data


# ============================================================================
# ROUTES
# ============================================================================

@router.post("/upload", response_model=VideoUploadResponse)
async def upload_video(
    request: Request,
    video: UploadFile = File(...),
    session_name: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload and analyze a workout video.
    
    This endpoint:
    1. Validates the video file
    2. Uploads to Supabase Storage
    3. Creates a session record
    4. Runs AI analysis (synchronous, takes 1-3 minutes)
    5. AUTO-DETECTS the exercise type from the video
    6. Saves the report
    7. Updates the session
    8. Returns complete results
    
    Args:
        video: Video file (multipart/form-data)
        session_name: Optional session name
        current_user: Injected by dependency
        
    Returns:
        VideoUploadResponse with complete analysis results
    """
    temp_path = None
    session_id = None
    
    try:
        # STEP 1: Validate inputs
        logger.info(f"Received upload request from user {current_user['id']}")
        
        # Check file extension
        file_ext = Path(video.filename).suffix.lower()
        if file_ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"File type not supported. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
            )
        
        # Generate session name if not provided
        if not session_name:
            date_str = datetime.now().strftime("%B %d, %Y")
            session_name = f"Workout Session - {date_str}"
        
        # STEP 2: Read file into memory
        file_bytes = await video.read()
        file_size = len(file_bytes)
        
        if file_size == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        
        if file_size > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size is {MAX_FILE_SIZE_BYTES // (1024*1024)}MB"
            )
        
        logger.info(f"Received video: {video.filename}, size: {file_size/1024/1024:.1f}MB")
        
        # STEP 3: Save to temp disk for OpenCV
        temp_filename = f"{uuid.uuid4()}{file_ext}"
        temp_path = TEMP_DIR / temp_filename
        
        with open(temp_path, "wb") as f:
            f.write(file_bytes)
        
        logger.info(f"Saved to temp: {temp_path}")
        
        # STEP 4: Upload to Supabase Storage (private bucket)
        video_storage_path = await upload_video_to_storage(
            file_bytes=file_bytes,
            filename=video.filename,
            user_id=current_user["id"]
        )
        
        logger.info(f"Uploaded to storage: {video_storage_path}")
        
        # STEP 5: Create session record (status will be set by database default)
        session_id = await create_session_record(
            user_id=current_user["id"],
            exercise_type="unknown",  # Will be updated after analysis
            session_name=session_name,
            video_storage_path=video_storage_path
        )
        
        logger.info(f"Created session: {session_id}")
        
        # STEP 6: Check if model is loaded
        if not request.app.state.model_loaded:
            raise HTTPException(
                status_code=503,
                detail="AI model is not loaded. Contact administrator."
            )
        
        # STEP 7: Run AI analysis (CPU-bound, use executor)
        # Exercise type will be AUTO-DETECTED by the AI
        logger.info(f"Starting AI analysis for session {session_id}")
        
        loop = asyncio.get_event_loop()
        analysis_result = await loop.run_in_executor(
            None,
            lambda: analyze_video(
                file_path=str(temp_path),
                user_id=current_user["id"],
                session_name=session_name,
                model=request.app.state.model,
                labels=request.app.state.labels
            )
        )
        
        logger.info(f"Analysis complete for session {session_id}")
        
        # STEP 8: Save report to database
        report = analysis_result["report"]
        metrics = analysis_result["metrics"]
        
        report_id = await save_report_record(
            session_id=session_id,
            user_id=current_user["id"],
            report=report,
            exercise_type=metrics["exercise_detected"],
            form_score=metrics["form_score"],
            performance_rating=metrics["performance_rating"],
            total_mistakes=metrics["total_mistakes"]
        )
        
        logger.info(f"Report saved: {report_id}")
        
        # STEP 9: Update session record with final metrics
        await update_session_after_analysis(
            session_id=session_id,
            form_score=metrics["form_score"],
            performance_rating=metrics["performance_rating"],
            total_mistakes=metrics["total_mistakes"],
            total_frames_processed=metrics["total_frames_processed"],
            duration_seconds=metrics["duration_seconds"],
            exercise_detected=metrics["exercise_detected"],
            status="completed"
        )
        
        logger.info(f"Session {session_id} updated to completed")
        
        # STEP 10: Return response
        return VideoUploadResponse(
            session_id=session_id,
            report_id=report_id,
            message="Video analyzed successfully",
            report=report,
            video_storage_path=video_storage_path,
            metrics=metrics
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
        
    except Exception as e:
        # Log the full error
        logger.error(f"Analysis failed: {str(e)}", exc_info=True)
        
        # Update session status to failed if it was created
        if session_id:
            try:
                await update_session_after_analysis(
                    session_id=session_id,
                    form_score=0,
                    performance_rating="needs_improvement",
                    total_mistakes=0,
                    total_frames_processed=0,
                    duration_seconds=0,
                    exercise_detected="unknown",
                    status="failed"
                )
            except Exception as cleanup_error:
                logger.error(f"Failed to create error report: {cleanup_error}")
        
        # Return error to client
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(e)}"
        )
        
    finally:
        # ALWAYS cleanup temp file
        if temp_path and temp_path.exists():
            try:
                os.remove(temp_path)
                logger.info(f"Cleaned up temp file: {temp_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp file: {e}")


@router.get("/session/{session_id}/status", response_model=AnalysisStatusResponse)
async def get_session_status_endpoint(
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get the status of a video analysis session.
    
    This endpoint is used for polling during analysis.
    
    Args:
        session_id: UUID of the session
        current_user: Injected by dependency
        
    Returns:
        AnalysisStatusResponse with current status
    """
    result = await get_session_status(session_id, current_user["id"])
    
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")
    
    status = result["status"]
    
    # Generate appropriate message
    if status == "processing":
        message = "Your video is being analyzed..."
    elif status == "completed":
        message = "Analysis complete!"
    elif status == "failed":
        message = "Analysis failed. Please try again."
    else:
        message = f"Status: {status}"
    
    return AnalysisStatusResponse(
        session_id=session_id,
        status=status,
        message=message
    )
