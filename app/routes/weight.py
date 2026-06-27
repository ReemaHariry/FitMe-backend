"""
Weight Tracking Routes

Handles weight logging and history retrieval.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional
import logging
from app.services.supabase_service import get_weight_logs, log_weight, delete_weight_log
from app.routes.users import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class LogWeightRequest(BaseModel):
    """Request body for logging weight"""
    weight_kg: float = Field(..., ge=10, le=300, description="Weight in kilograms")
    note: Optional[str] = Field(None, max_length=500, description="Optional note")


class WeightLogResponse(BaseModel):
    """Response for a single weight log"""
    id: str
    weight_kg: float
    logged_at: str
    note: Optional[str]
    created_at: str


class MessageResponse(BaseModel):
    """Generic message response"""
    message: str


# ============================================================================
# ROUTES
# ============================================================================

@router.get("/logs", response_model=list[WeightLogResponse])
async def get_logs(
    limit: int = 10,
    current_user: dict = Depends(get_current_user)
):
    """
    Get weight log history for the current user.
    
    Query params:
    - limit: Number of entries to return (default 10, max 30)
    
    Returns logs ordered by date ASC (oldest first) for charting.
    """
    user_id = current_user["id"]
    
    try:
        # Validate and cap limit
        if limit < 1:
            limit = 10
        if limit > 30:
            limit = 30
        
        logs = get_weight_logs(user_id, limit)
        return logs
        
    except Exception as e:
        logger.error(f"Failed to get weight logs: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve weight logs"
        )


@router.post("/logs", response_model=WeightLogResponse, status_code=status.HTTP_201_CREATED)
async def create_log(
    data: LogWeightRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Log a new weight entry.
    
    Body:
    - weight_kg: Weight in kilograms (20-500)
    - note: Optional note (max 500 chars)
    
    Returns the created log entry.
    """
    user_id = current_user["id"]
    
    try:
        log_entry = log_weight(
            user_id=user_id,
            weight_kg=data.weight_kg,
            note=data.note
        )
        
        logger.info(f"Weight logged: {data.weight_kg} kg for user {user_id}")
        return log_entry
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to log weight: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to log weight"
        )


@router.delete("/logs/{log_id}", response_model=MessageResponse)
async def delete_log(
    log_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a weight log entry.
    
    Security: Verifies the log belongs to the current user.
    """
    user_id = current_user["id"]
    
    try:
        delete_weight_log(log_id, user_id)
        
        return MessageResponse(message="Weight log deleted successfully")
        
    except Exception as e:
        logger.error(f"Failed to delete weight log: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Weight log not found or unauthorized"
        )
