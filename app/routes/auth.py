"""
Authentication Routes

Handles user registration, login, logout, and token verification.
Uses Supabase Auth for all authentication operations.
"""

from fastapi import APIRouter, HTTPException, Header, status
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from app.services.supabase_service import get_supabase_client, get_profile, verify_token


# ============================================================================
# PYDANTIC MODELS (Request/Response schemas)
# ============================================================================

class RegisterRequest(BaseModel):
    """Request body for user registration"""
    name: str = Field(..., min_length=2, max_length=100, description="User's full name")
    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., min_length=8, description="User's password (min 8 characters)")


class LoginRequest(BaseModel):
    """Request body for user login"""
    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., min_length=6, description="User's password")


class UserResponse(BaseModel):
    """User object returned in auth responses"""
    id: str
    name: str
    email: str
    onboarding_complete: bool


class AuthResponse(BaseModel):
    """Response for successful login/register"""
    token: str
    user: UserResponse


class MessageResponse(BaseModel):
    """Generic message response"""
    message: str


# ============================================================================
# ROUTER SETUP
# ============================================================================

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


# ============================================================================
# HELPER FUNCTION: Extract Bearer Token
# ============================================================================

def get_token_from_header(authorization: Optional[str]) -> str:
    """
    Extract JWT token from Authorization header.
    
    Args:
        authorization: Authorization header value (e.g., "Bearer abc123...")
        
    Returns:
        str: The extracted token
        
    Raises:
        HTTPException: If header is missing or malformed
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
    
    return parts[1]


# ============================================================================
# ENDPOINT: POST /auth/register
# ============================================================================

@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest):
    """
    Register a new user.
    
    Process:
    1. Call Supabase auth.sign_up() with email and password
    2. Pass user's name in metadata so the database trigger can use it
    3. The trigger automatically creates a profile row
    4. Return token and user object
    
    Errors:
    - 409: Email already in use
    - 400: Weak password or other validation error
    """
    try:
        supabase = get_supabase_client()
        
        print(f"🔍 Attempting to register user: {data.email}")
        
        # Sign up user with Supabase Auth
        # user_metadata is stored in auth.users and accessible in triggers
        response = supabase.auth.sign_up({
            "email": data.email,
            "password": data.password,
            "options": {
                "data": {
                    "full_name": data.name
                }
            }
        })
        
        print(f"📦 Supabase response: {response}")
        
        # Check if signup was successful
        if not response.user:
            print(f"❌ No user in response")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Registration failed. Please try again."
            )
        
        # Check if email already exists (Supabase returns user but no session)
        if not response.session:
            print(f"❌ No session in response - email may already exist")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists"
            )
        
        print(f"✅ User created successfully: {response.user.id}")
        
        # Get the profile (should be auto-created by trigger)
        profile = get_profile(response.user.id)
        print(f"📋 Profile: {profile}")
        
        # Return token and user data
        return AuthResponse(
            token=response.session.access_token,
            user=UserResponse(
                id=response.user.id,
                name=data.name,
                email=response.user.email,
                onboarding_complete=profile.get("onboarding_complete", False) if profile else False
            )
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        print(f"❌ Registration error: {type(e).__name__}: {str(e)}")
        error_message = str(e).lower()
        
        # Handle specific Supabase errors
        if "already registered" in error_message or "already exists" in error_message:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists"
            )
        elif "password" in error_message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password is too weak. Please use at least 8 characters."
            )
        else:
            # Generic error
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Database error saving new user"
            )


# ============================================================================
# ENDPOINT: POST /auth/login
# ============================================================================

@router.post("/login", response_model=AuthResponse)
async def login(data: LoginRequest):
    """
    Login an existing user.
    
    Process:
    1. Call Supabase auth.sign_in_with_password()
    2. Fetch user's profile to get onboarding_complete status
    3. Return token and user object
    
    The onboarding_complete field tells React whether to redirect to:
    - /onboarding (if false)
    - /dashboard (if true)
    
    Errors:
    - 401: Invalid email or password
    - 400: Email not confirmed
    """
    try:
        supabase = get_supabase_client()
        
        # Attempt to sign in
        response = supabase.auth.sign_in_with_password({
            "email": data.email,
            "password": data.password
        })
        
        # Check if login was successful
        if not response.user or not response.session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        # Fetch user's profile to get onboarding status
        profile = get_profile(response.user.id)
        
        # Get user's name from metadata or profile
        user_name = response.user.user_metadata.get("full_name", "User")
        if profile and profile.get("full_name"):
            user_name = profile["full_name"]
        
        # Return token and user data
        return AuthResponse(
            token=response.session.access_token,
            user=UserResponse(
                id=response.user.id,
                name=user_name,
                email=response.user.email,
                onboarding_complete=profile.get("onboarding_complete", False) if profile else False
            )
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        error_message = str(e).lower()
        
        # Handle specific Supabase errors
        if "invalid" in error_message or "credentials" in error_message:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        elif "not confirmed" in error_message or "email not confirmed" in error_message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please confirm your email first"
            )
        else:
            # Generic error - don't reveal too much
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )


# ============================================================================
# ENDPOINT: GET /auth/me
# ============================================================================

@router.get("/me", response_model=UserResponse)
async def get_current_user(authorization: Optional[str] = Header(None)):
    """
    Get current authenticated user's data.
    
    This endpoint verifies the JWT token and returns user information.
    Used by React to:
    - Restore user session on page reload
    - Verify token is still valid
    - Get updated onboarding status
    
    Requires: Authorization header with Bearer token
    
    Errors:
    - 401: Missing, invalid, or expired token
    """
    # Extract token from header
    token = get_token_from_header(authorization)
    
    # Verify token and get user data
    user_data = verify_token(token)
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired, please log in again"
        )
    
    # Fetch profile to get onboarding status
    profile = get_profile(user_data["id"])
    
    # Get user's name
    user_name = user_data.get("user_metadata", {}).get("full_name", "User")
    if profile and profile.get("full_name"):
        user_name = profile["full_name"]
    
    return UserResponse(
        id=user_data["id"],
        name=user_name,
        email=user_data["email"],
        onboarding_complete=profile.get("onboarding_complete", False) if profile else False
    )


# ============================================================================
# ENDPOINT: POST /auth/logout
# ============================================================================

@router.post("/logout", response_model=MessageResponse)
async def logout(authorization: Optional[str] = Header(None)):
    """
    Logout current user.
    
    This calls Supabase's sign_out() to invalidate the session.
    React also clears localStorage on its side.
    
    Requires: Authorization header with Bearer token
    
    Note: Even if this fails, React will clear localStorage anyway,
    so the user will be logged out on the frontend.
    """
    try:
        # Extract token from header
        token = get_token_from_header(authorization)
        
        # Sign out from Supabase
        supabase = get_supabase_client()
        supabase.auth.sign_out()
        
        return MessageResponse(message="Logged out successfully")
        
    except Exception as e:
        # Even if logout fails on backend, return success
        # Frontend will clear localStorage anyway
        return MessageResponse(message="Logged out successfully")
