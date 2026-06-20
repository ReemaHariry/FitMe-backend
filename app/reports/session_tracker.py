"""
Session Tracker Module
Tracks mistakes during a workout session and maintains event history.
This module is backend-focused and should be integrated with your FastAPI service.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Optional
from collections import defaultdict


@dataclass
class MistakeEvent:
    """Represents a single mistake detected during the session."""
    timestamp: float  # Seconds from session start
    frame_number: int
    exercise_type: str  # e.g., "squat", "push_up", "sit_up"
    mistake_type: str  # e.g., "back_not_straight", "knees_past_toes"
    mistake_message: str  # Human-readable message
    severity: str = "medium"  # "low", "medium", "high"
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class SessionTracker:
    """
    Tracks all mistakes and events during a workout session.
    
    Usage:
        tracker = SessionTracker(session_id="abc123", user_id="user456")
        tracker.start_session()
        
        # During workout
        tracker.record_mistake(
            timestamp=12.5,
            frame_number=375,
            exercise_type="squat",
            mistake_type="knees_past_toes",
            mistake_message="Knees too far past toes"
        )
        
        # At end
        tracker.end_session()
        report = tracker.get_session_summary()
    """
    
    session_id: str
    user_id: str
    session_name: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    mistakes: List[MistakeEvent] = field(default_factory=list)
    total_frames_processed: int = 0
    frames_with_pose: int = 0  # NEW: Track frames where pose was detected
    exercise_detected: Optional[str] = None
    cooldown_seconds: float = 1.0
    last_mistake_time: Dict[str, float] = field(default_factory=dict)

    def start_session(self, session_name: Optional[str] = None):
        """Initialize session tracking."""
        self.start_time = datetime.now()
        self.session_name = session_name or f"Workout {self.start_time.strftime('%Y-%m-%d %H:%M')}"
        self.mistakes = []
        self.total_frames_processed = 0
        self.last_mistake_time = {}
        self.frames_with_pose = 0  # NEW: Reset pose counter

    def record_mistake(
        self,
        timestamp: float,
        frame_number: int,
        exercise_type: str,
        mistake_type: str,
        mistake_message: str,
        severity: str = "medium"
    ) -> bool:
        """
        Record a detected mistake, unless the same mistake_type was just
        recorded within cooldown_seconds (using video/session timestamp,
        not wall-clock time). This collapses a sustained bad-form condition
        spanning many consecutive frames into a single event.

        Args:
            timestamp: Seconds from session/video start
            frame_number: Frame number in video/stream
            exercise_type: Type of exercise being performed
            mistake_type: Categorized mistake identifier
            mistake_message: Human-readable description
            severity: "low", "medium", or "high"

        Returns:
            True if the mistake was recorded, False if suppressed by cooldown.
        """
        last_time = self.last_mistake_time.get(mistake_type)
        if last_time is not None and (timestamp - last_time) < self.cooldown_seconds:
            return False

        event = MistakeEvent(
            timestamp=timestamp,
            frame_number=frame_number,
            exercise_type=exercise_type,
            mistake_type=mistake_type,
            mistake_message=mistake_message,
            severity=severity
        )
        self.mistakes.append(event)
        self.last_mistake_time[mistake_type] = timestamp

        # Track the exercise type
        if not self.exercise_detected:
            self.exercise_detected = exercise_type

        return True
    
    def increment_frame_count(self):
        """Increment the total frames processed counter."""
        self.total_frames_processed += 1
    
    def increment_pose_count(self):
        """Increment counter for frames where a valid pose was detected."""
        self.frames_with_pose += 1
    
    def end_session(self):
        """Mark session as ended."""
        self.end_time = datetime.now()
    
    def get_duration_seconds(self) -> float:
        """Calculate session duration in seconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0
    
    def get_mistake_count(self) -> int:
        """Get total number of mistakes recorded."""
        return len(self.mistakes)
    
    def get_mistakes_by_type(self) -> Dict[str, List[MistakeEvent]]:
        """Group mistakes by type."""
        grouped = defaultdict(list)
        for mistake in self.mistakes:
            grouped[mistake.mistake_type].append(mistake)
        return dict(grouped)
    
    def get_mistake_frequency(self) -> Dict[str, int]:
        """Get frequency count for each mistake type."""
        frequency = defaultdict(int)
        for mistake in self.mistakes:
            frequency[mistake.mistake_type] += 1
        return dict(frequency)
    
    def get_high_frequency_mistakes(self, threshold: int = 5) -> List[str]:
        """
        Identify mistakes that occurred frequently (potential injury risk).
        
        Args:
            threshold: Minimum occurrences to be considered high-frequency
            
        Returns:
            List of mistake types that exceeded threshold
        """
        frequency = self.get_mistake_frequency()
        return [
            mistake_type 
            for mistake_type, count in frequency.items() 
            if count >= threshold
        ]
    
    def get_session_summary(self) -> dict:
        """
        Get a basic summary of the session.
        This is used by the report generator.
        """
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "session_name": self.session_name,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.get_duration_seconds(),
            "exercise_detected": self.exercise_detected,
            "total_frames_processed": self.total_frames_processed,
            "frames_with_pose": self.frames_with_pose,  # NEW: Include pose count
            "total_mistakes": self.get_mistake_count(),
            "mistakes": [m.to_dict() for m in self.mistakes],
            "mistake_frequency": self.get_mistake_frequency(),
            "high_frequency_mistakes": self.get_high_frequency_mistakes()
        }
    
    def clear(self):
        """Clear all session data (useful for reusing tracker instance)."""
        self.mistakes = []
        self.total_frames_processed = 0
        self.frames_with_pose = 0  # NEW: Reset pose counter
        self.start_time = None
        self.end_time = None
        self.exercise_detected = None
        self.last_mistake_time = {}
