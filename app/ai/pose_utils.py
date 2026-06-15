"""
Pose Utility Functions
Shared utilities for pose detection and feature extraction.
"""
import numpy as np
import mediapipe as mp


def extract_pose_features(results) -> np.ndarray | None:
    """
    Extract pose features from MediaPipe Holistic results.
    
    Args:
        results: MediaPipe Holistic results object
        
    Returns:
        np.ndarray of shape (99,) containing x,y,z coordinates for 33 landmarks
        OR None if no pose detected
    """
    if results.pose_landmarks is None:
        return None
    
    # Extract x, y, z for all 33 pose landmarks
    features = []
    for landmark in results.pose_landmarks.landmark:
        features.extend([landmark.x, landmark.y, landmark.z])
    
    return np.array(features, dtype=np.float32)


def init_mediapipe() -> tuple:
    """
    Initialize MediaPipe Holistic components.
    
    Returns:
        Tuple of (holistic_class, drawing_utils, drawing_styles)
    """
    holistic_class = mp.solutions.holistic.Holistic
    drawing_utils = mp.solutions.drawing_utils
    drawing_styles = mp.solutions.drawing_styles
    
    return holistic_class, drawing_utils, drawing_styles


def calculate_form_score(report: dict, total_frames: int) -> int:
    """
    Calculate a numeric form score (0-100) from the report.
    
    Since ReportGenerator does not produce a numeric form_score,
    we calculate it based on mistake frequency and performance rating.
    
    Args:
        report: Complete report dict from ReportGenerator
        total_frames: Total frames processed in the session
        
    Returns:
        Integer form score from 0 to 100
    """
    # Check if this is a "no pose detected" report
    if report.get("no_pose_detected"):
        return 0  # Return 0 score for sessions with no pose detected
    
    total_mistakes = report["statistics"]["total_mistakes"]
    performance_rating = report["overall_summary"]["performance_rating"]
    
    # Base calculation: mistakes per frame ratio
    if total_frames == 0:
        form_score = 100
    else:
        mistake_ratio = total_mistakes / max(total_frames, 1)
        # Scale: each mistake per frame reduces score significantly
        # Using 500 as multiplier means ~2 mistakes per 1000 frames = 100 score
        form_score = max(0, min(100, int(100 - (mistake_ratio * 500))))
    
    # Adjust based on performance rating to ensure consistency
    if performance_rating == "excellent":
        form_score = max(form_score, 90)
    elif performance_rating == "good":
        form_score = max(form_score, 75)
    elif performance_rating == "fair":
        form_score = max(form_score, 50)
    else:  # needs_improvement
        form_score = min(form_score, 49)
    
    return form_score
