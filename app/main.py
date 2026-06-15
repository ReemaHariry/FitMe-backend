"""
AI Fitness Trainer API - Main Application Entry Point

This is the core FastAPI application that handles all HTTP requests.
"""

import os
import numpy as np
import logging
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import settings

# Configure TensorFlow and MediaPipe before importing
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"  # Suppress TensorFlow warnings
os.environ["MEDIAPIPE_DISABLE_GPU"] = "1"  # Use CPU only

# Import routers
from app.routes import auth, users, reports, videos, sessions, dashboard, weight  # NEW: Added weight
from app.websockets.live_handler import handle_live_session

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
    Code before 'yield' runs on startup, code after 'yield' runs on shutdown.
    """
    logger.info("AI Fitness Trainer API is starting up...")
    logger.info(f"Model directory: {settings.model_dir}")
    logger.info(f"Environment: {settings.environment}")
    
    model_dir = settings.model_dir
    model_path = os.path.join(model_dir, "best_model.keras")
    labels_path = os.path.join(model_dir, "label_encoder.npy")
    alt_model_path = os.path.join(model_dir, "lstm_model.keras")
    
    # Download model files from Supabase Storage if they are not found locally
    if not os.path.exists(model_path) or not os.path.exists(labels_path):
        logger.info("Model files not found locally. Downloading from Supabase Storage...")
        
        try:
            os.makedirs(model_dir, exist_ok=True)
            
            from supabase import create_client
            
            storage_client = create_client(
                settings.supabase_url,
                settings.supabase_service_key
            )
            
            files_to_download = [
                ("best_model.keras", model_path),
                ("label_encoder.npy", labels_path),
                ("lstm_model.keras", alt_model_path),
            ]
            
            for storage_file_name, local_file_path in files_to_download:
                if not os.path.exists(local_file_path):
                    logger.info(f"Downloading {storage_file_name}...")
                    file_bytes = storage_client.storage.from_("ai-models").download(storage_file_name)
                    
                    with open(local_file_path, "wb") as f:
                        f.write(file_bytes)
                    
                    logger.info(f"{storage_file_name} downloaded successfully")
        
        except Exception as e:
            logger.error(f"Failed to download model files from Supabase Storage: {e}")
            app.state.model = None
            app.state.labels = None
            app.state.model_loaded = False
            yield
            return
    
    # Load the model
    try:
        import tensorflow as tf
        
        logger.info(f"Loading model from {model_path}...")
        
        try:
            app.state.model = tf.keras.models.load_model(model_path, compile=False)
        except Exception as e1:
            logger.warning(f"Failed to load best_model.keras: {e1}")
            
            if os.path.exists(alt_model_path):
                logger.info(f"Trying alternative model: {alt_model_path}")
                app.state.model = tf.keras.models.load_model(alt_model_path, compile=False)
            else:
                raise e1
        
        app.state.labels = np.load(labels_path, allow_pickle=True)
        app.state.labels = np.array([str(x) for x in app.state.labels])
        app.state.model_loaded = True
        
        logger.info(f"Model loaded successfully. Classes: {app.state.labels}")
    
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        app.state.model = None
        app.state.labels = None
        app.state.model_loaded = False
    
    yield
    
    logger.info("AI Fitness Trainer API is shutting down...")


# Create the FastAPI application instance
app = FastAPI(
    title="AI Fitness Trainer API",
    version="1.0.0",
    description="Backend API for AI-powered fitness training and form correction",
    lifespan=lifespan  # Attach the lifespan context manager
)


# Configure CORS (Cross-Origin Resource Sharing)
# This allows your React frontend to make requests to this API
app.add_middleware(
    CORSMiddleware,
    # Allow requests from these origins (your React dev servers)
    allow_origins=settings.allowed_origins.split(","),    
    # Allow cookies and authentication headers
    allow_credentials=True,
    # Allow all HTTP methods (GET, POST, PUT, DELETE, etc.)
    allow_methods=["*"],
    # Allow all headers
    allow_headers=["*"],
)


# ============================================================================
# ROUTERS
# ============================================================================

# Include authentication routes
app.include_router(auth.router)

# Include user profile routes
app.include_router(users.router)

# Include reports routes
app.include_router(reports.router)

# Include video upload routes
app.include_router(videos.router, prefix="/videos", tags=["videos"])

# Include live session routes
app.include_router(sessions.router, prefix="/sessions", tags=["sessions"])

# Include dashboard statistics routes
app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])

# NEW: Include weight tracking routes
app.include_router(weight.router, prefix="/weight", tags=["weight"])


# ============================================================================
# HEALTH CHECK ENDPOINT
# ============================================================================

@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    
    Returns the API status and confirms the server is running.
    This endpoint does NOT require authentication - it's public.
    
    Returns:
        dict: Status message confirming API is operational
    """
    from app.services.session_service import get_active_session_count
    
    return {
        "status": "ok",
        "message": "AI Fitness Trainer API is running",
        "version": "1.0.0",
        "environment": settings.environment,
        "model_loaded": app.state.model_loaded if hasattr(app.state, 'model_loaded') else False,
        "active_live_sessions": get_active_session_count()
    }


# ============================================================================
# ROOT ENDPOINT
# ============================================================================

@app.get("/")
async def root():
    """
    Root endpoint - API welcome message.
    
    Returns:
        dict: Welcome message with links to documentation
    """
    return {
        "message": "Welcome to AI Fitness Trainer API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }


# ============================================================================
# FUTURE ROUTES WILL BE ADDED HERE
# ============================================================================
# Example:
# from app.routes import auth, workouts, ai_inference
# app.include_router(auth.router)
# app.include_router(workouts.router)
# app.include_router(ai_inference.router)


# ============================================================================
# WEBSOCKET ENDPOINT
# ============================================================================

@app.websocket("/ws/live/{session_id}")
async def websocket_live(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for live training sessions.
    
    React connects here after calling POST /sessions/start.
    Streams frames and receives real-time feedback.
    
    Args:
        websocket: WebSocket connection
        session_id: UUID of the session
    """
    await handle_live_session(websocket, session_id)
