"""
Configuration Management

This module handles all environment variables and application settings.
Uses pydantic-settings to automatically load from .env file and validate types.
"""

from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import Optional, List


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    All settings can be overridden by creating a .env file in the backend/ directory.
    """
    
    # Pydantic v2 configuration
    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=False,
        protected_namespaces=()  # Allow model_* field names
    )
    
    # Supabase Database Configuration
    # Get these from your Supabase project dashboard
    supabase_url: str = ""
    supabase_service_key: str = ""
    
    # AI Model Configuration
    # Path to the directory containing your trained pose detection models
    model_dir: str = "./trained_pose_model"
    
    # Security Configuration
    # IMPORTANT: Change this in production! Used for JWT token signing
    secret_key: str = "change-this-in-production-use-openssl-rand-hex-32"
    
    # Environment Configuration
    # Options: "development", "staging", "production"
    environment: str = "development"
    
    # CORS Configuration
    # Frontend URLs that are allowed to make requests to this API
    frontend_url: str = "http://localhost:3000"
    frontend_url_alt: str = "http://localhost:5173"
    cors_origins: List[str] = ["http://localhost:3000", "http://localhost:5173"]
    
    # File Upload Configuration (Feature 6)
    max_upload_size_mb: int = 500  # Maximum video upload size in MB
    temp_video_dir: str = "/tmp/fitpose_videos"  # Temporary directory for video processing


# Create a single instance of settings that will be imported throughout the app
# This ensures all modules use the same configuration
settings = Settings()
