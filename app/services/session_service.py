"""
Session Service Module

Manages active live sessions in server memory.
Each live session has a SessionTracker object stored in a dict.
The WebSocket handler reads/writes to this dict.

IMPORTANT: This is server memory (Python dict), NOT the database.
The database only gets written at session start and session end.
During the session, everything lives in memory for speed.
"""

import uuid
import logging
from datetime import datetime
from typing import Optional, Dict
from app.reports.session_tracker import SessionTracker

logger = logging.getLogger(__name__)

# This dict holds all active sessions
# Key: session_id (string UUID)
# Value: dict with tracker and metadata
_active_sessions: Dict[str, dict] = {}


def create_live_session(user_id: str, session_name: str) -> tuple[str, SessionTracker]:
    """
    Creates a new live session in memory.
    
    Returns (session_id, tracker).
    Does NOT write to the database yet.
    The database write happens in routes/sessions.py.
    
    Args:
        user_id: UUID of the user
        session_name: Human-readable session name
        
    Returns:
        Tuple of (session_id, tracker)
    """
    session_id = str(uuid.uuid4())
    tracker = SessionTracker(session_id=session_id, user_id=user_id)
    tracker.start_session(session_name=session_name)
    
    _active_sessions[session_id] = {
        "tracker": tracker,
        "user_id": user_id,
        "created_at": datetime.now(),
        "feature_buffer": None,  # Set by live_handler.py
        "last_activity": datetime.now()
    }
    
    logger.info(f"Live session created: {session_id}")
    return session_id, tracker


def get_live_session(session_id: str) -> Optional[dict]:
    """
    Returns the session dict for a given session_id.
    
    Args:
        session_id: UUID of the session
        
    Returns:
        Dict containing tracker and metadata, or None if not found
    """
    return _active_sessions.get(session_id)


def get_tracker(session_id: str) -> Optional[SessionTracker]:
    """
    Returns just the tracker for convenience.
    
    Args:
        session_id: UUID of the session
        
    Returns:
        SessionTracker instance or None if not found
    """
    session = _active_sessions.get(session_id)
    if session:
        return session["tracker"]
    return None


def update_last_activity(session_id: str) -> None:
    """
    Updates the last_activity timestamp.
    Used to detect stale sessions.
    
    Args:
        session_id: UUID of the session
    """
    if session_id in _active_sessions:
        _active_sessions[session_id]["last_activity"] = datetime.now()


def end_live_session(session_id: str) -> Optional[SessionTracker]:
    """
    Removes session from memory and returns the tracker.
    The tracker contains all recorded mistakes.
    Called by routes/sessions.py when the user ends the session.
    
    Args:
        session_id: UUID of the session
        
    Returns:
        SessionTracker with all recorded data, or None if not found
    """
    session = _active_sessions.pop(session_id, None)
    if session:
        tracker = session["tracker"]
        tracker.end_session()
        logger.info(f"Live session ended: {session_id}")
        return tracker
    return None


def get_active_session_count() -> int:
    """
    Returns number of active sessions.
    Used in /health endpoint.
    
    Returns:
        Number of active sessions
    """
    return len(_active_sessions)


def cleanup_stale_sessions(max_age_minutes: int = 60) -> int:
    """
    Removes sessions that have been inactive for too long.
    Call this periodically or on server shutdown.
    
    Args:
        max_age_minutes: Maximum age in minutes before session is considered stale
        
    Returns:
        Number of sessions removed
    """
    from datetime import timedelta
    
    cutoff = datetime.now() - timedelta(minutes=max_age_minutes)
    stale = [
        sid for sid, s in _active_sessions.items()
        if s["last_activity"] < cutoff
    ]
    
    for sid in stale:
        _active_sessions.pop(sid, None)
        logger.warning(f"Removed stale session: {sid}")
    
    return len(stale)
