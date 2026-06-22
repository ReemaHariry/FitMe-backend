"""
AI Coach Routes

Chat endpoints for the FitMe AI Coach fitness chatbot.
All endpoints are protected and operate on the logged-in user only.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.routes.users import get_current_user
from app.services import ai_coach_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/coach", tags=["AI Coach"])


# ============================================================================
# MODELS
# ============================================================================

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="User message")


class ChatResponse(BaseModel):
    reply: str


class MessageResponse(BaseModel):
    message: str


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """Send a message to the AI Coach and get a personalized fitness reply."""
    user_id = current_user.get("id") or current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")

    if not ai_coach_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI Coach is not configured. Please set GROQ_API_KEY on the server.",
        )

    try:
        reply = ai_coach_service.chat(user_id, body.message)
        return ChatResponse(reply=reply)
    except Exception as e:
        logger.error(f"AI Coach chat error for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The AI Coach ran into a problem. Please try again.",
        )


@router.post("/reset", response_model=MessageResponse)
async def reset(current_user: dict = Depends(get_current_user)):
    """Clear the current user's conversation memory and start fresh."""
    user_id = current_user.get("id") or current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")

    ai_coach_service.reset_user_memory(user_id)
    return MessageResponse(message="Conversation reset.")
