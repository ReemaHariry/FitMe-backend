"""
User Profile Routes

Handles user profile management, onboarding completion, and progress photos.
"""

from fastapi import APIRouter, HTTPException, Header, Depends, status, UploadFile, File, Form
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date
from app.services.supabase_service import (
    get_supabase_client,
    save_profile,
    get_profile,
    verify_token,
    get_progress_photos,
    save_progress_photo,
    delete_progress_photo,
    upload_progress_photo_to_storage
)


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class ProfileUpdateRequest(BaseModel):
    """Request body for updating user profile (onboarding data)"""
    gender: str = Field(..., pattern="^(male|female)$", description="User's gender")
    age: int = Field(..., ge=13, le=100, description="User's age")
    height: float = Field(..., ge=100, le=250, description="Height in cm")
    weight: float = Field(..., ge=30, le=300, description="Weight in kg")
    fitness_goal: str = Field(..., pattern="^(lose_weight|build_muscle|maintain)$")
    training_days_per_week: int = Field(..., ge=1, le=7)
    preferred_workout_duration: int = Field(..., ge=15, le=180, description="Duration in minutes")


class ProfileResponse(BaseModel):
    """Response after saving profile"""
    message: str
    onboarding_complete: bool


class ProfileDataResponse(BaseModel):
    """Full profile data response"""
    id: str
    user_id: str
    full_name: Optional[str]
    gender: Optional[str]
    age: Optional[int]
    height: Optional[float]
    weight: Optional[float]
    fitness_goal: Optional[str]
    training_days_per_week: Optional[int]
    preferred_workout_duration: Optional[int]
    onboarding_complete: bool


class ProgressPhotoResponse(BaseModel):
    """Progress photo record"""
    id: str
    user_id: str
    photo_url: str
    storage_path: str
    photo_type: str
    taken_at: str
    created_at: str


class ProgressPhotoUploadResponse(BaseModel):
    """Response after uploading a progress photo"""
    message: str
    photo: ProgressPhotoResponse


# ============================================================================
# DEPENDENCY: Get Current User
# ============================================================================

async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """
    Dependency to extract and verify the current user from JWT token.
    
    This is reusable across all protected endpoints.
    
    Args:
        authorization: Authorization header with Bearer token
        
    Returns:
        dict: User data from token
        
    Raises:
        HTTPException: If token is missing, invalid, or expired
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token format"
        )
    
    token = parts[1]
    user_data = verify_token(token)
    
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired, please log in again"
        )
    
    return user_data


# ============================================================================
# ROUTER SETUP
# ============================================================================

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)


# ============================================================================
# ENDPOINT: POST /users/profile
# ============================================================================

@router.post("/profile", response_model=ProfileResponse)
async def update_profile(
    data: ProfileUpdateRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Save or update user profile with onboarding data.
    
    This endpoint:
    1. Takes all onboarding form data
    2. Saves it to the profiles table
    3. Sets onboarding_complete = True
    4. Returns success message
    
    Uses upsert pattern: creates profile if doesn't exist, updates if it does.
    
    Requires: Authorization header with valid Bearer token
    """
    try:
        user_id = current_user["id"]
        
        # Prepare profile data
        profile_data = {
            "full_name": current_user.get("user_metadata", {}).get("full_name"),
            "gender": data.gender,
            "age": data.age,
            "height": data.height,
            "weight": data.weight,
            "fitness_goal": data.fitness_goal,
            "training_days_per_week": data.training_days_per_week,
            "preferred_workout_duration": data.preferred_workout_duration,
            "onboarding_complete": True,
        }
        
        # Save to database
        save_profile(user_id, profile_data)
        
        return ProfileResponse(
            message="Profile saved successfully",
            onboarding_complete=True
        )
        
    except Exception as e:
        print(f"Profile save error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save profile. Please try again."
        )


# ============================================================================
# ENDPOINT: GET /users/profile
# ============================================================================

@router.get("/profile", response_model=ProfileDataResponse)
async def get_user_profile(current_user: dict = Depends(get_current_user)):
    """
    Get current user's profile data.
    
    Returns all profile fields from the profiles table.
    
    Requires: Authorization header with valid Bearer token
    """
    try:
        user_id = current_user["id"]
        
        # Fetch profile from database
        profile = get_profile(user_id)
        
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile not found"
            )
        
        return ProfileDataResponse(**profile)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Profile fetch error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch profile"
        )


# ============================================================================
# ENDPOINT: GET /users/progress-photos
# ============================================================================

@router.get("/progress-photos", response_model=List[ProgressPhotoResponse])
async def get_user_progress_photos(current_user: dict = Depends(get_current_user)):
    """
    Get all progress photos for the current user.
    
    Returns photos ordered by created_at DESC (newest first).
    The frontend will show only the most recent photo for each type.
    
    Requires: Authorization header with valid Bearer token
    """
    try:
        user_id = current_user["id"]
        photos = get_progress_photos(user_id)
        return [ProgressPhotoResponse(**photo) for photo in photos]
    except Exception as e:
        print(f"Failed to fetch progress photos: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch progress photos"
        )


# ============================================================================
# ENDPOINT: POST /users/progress-photos
# ============================================================================

@router.post("/progress-photos", response_model=ProgressPhotoUploadResponse)
async def upload_progress_photo(
    photo: UploadFile = File(...),
    photo_type: str = Form(...),
    taken_at: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload a new progress photo.
    
    Process:
    1. Validate photo_type is 'front', 'side', or 'back'
    2. Validate taken_at is a valid date (YYYY-MM-DD)
    3. Upload photo to Supabase Storage (private bucket)
    4. Generate signed URL (expires in 1 year)
    5. Save record to progress_photos table
    6. Return the created photo record
    
    Args:
        photo: Image file (JPEG, PNG, WebP)
        photo_type: 'front', 'side', or 'back'
        taken_at: Date when photo was taken (YYYY-MM-DD)
        
    Requires: Authorization header with valid Bearer token
    """
    try:
        user_id = current_user["id"]
        
        # Validate photo_type
        if photo_type not in ['front', 'side', 'back']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="photo_type must be 'front', 'side', or 'back'"
            )
        
        # Validate taken_at is a valid date
        try:
            date.fromisoformat(taken_at)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="taken_at must be a valid date in YYYY-MM-DD format"
            )
        
        # Validate file type
        if not photo.content_type or not photo.content_type.startswith('image/'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must be an image (JPEG, PNG, or WebP)"
            )
        
        # Read file bytes
        file_bytes = await photo.read()
        
        # Validate file size (max 5MB)
        if len(file_bytes) > 5 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File size must be less than 5MB"
            )
        
        # Upload to storage
        signed_url, storage_path = upload_progress_photo_to_storage(
            file_bytes=file_bytes,
            filename=photo.filename or "photo.jpg",
            user_id=user_id,
            photo_type=photo_type
        )
        
        # Save record to database
        photo_record = save_progress_photo(
            user_id=user_id,
            photo_url=signed_url,
            storage_path=storage_path,
            photo_type=photo_type,
            taken_at=taken_at
        )
        
        return ProgressPhotoUploadResponse(
            message="Progress photo uploaded successfully",
            photo=ProgressPhotoResponse(**photo_record)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Failed to upload progress photo: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload progress photo: {str(e)}"
        )


# ============================================================================
# ENDPOINT: DELETE /users/progress-photos/{photo_id}
# ============================================================================

@router.delete("/progress-photos/{photo_id}")
async def delete_user_progress_photo(
    photo_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a progress photo.
    
    Process:
    1. Verify photo belongs to current user
    2. Delete photo from Supabase Storage
    3. Delete record from progress_photos table
    
    Security: Only the photo owner can delete their photos.
    
    Requires: Authorization header with valid Bearer token
    """
    try:
        user_id = current_user["id"]
        delete_progress_photo(photo_id, user_id)
        return {"message": "Progress photo deleted successfully"}
    except Exception as e:
        error_msg = str(e)
        if "not found" in error_msg.lower() or "unauthorized" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Progress photo not found"
            )
        print(f"Failed to delete progress photo: {error_msg}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete progress photo"
        )
