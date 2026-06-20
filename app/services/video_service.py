"""
Video Analysis Service
Runs the complete AI video analysis pipeline using OpenCV, MediaPipe, and TensorFlow.
"""
import os
import cv2
import numpy as np
import tensorflow as tf
import mediapipe as mp
import logging
import uuid
from datetime import datetime
from collections import deque
from typing import Optional
from collections import Counter

from app.ai.pose_utils import extract_pose_features, calculate_form_score
from app.ai.form_checks import check_pushup_form, check_squat_form, check_situp_form
from app.reports.session_tracker import SessionTracker
from app.reports.mistake_classifier import MistakeClassifier
from app.reports.report_generator import ReportGenerator

# Configure logger
logger = logging.getLogger(__name__)


def analyze_video(
    file_path: str,
    user_id: str,
    session_name: str,
    model,
    labels: np.ndarray
) -> dict:
    """
    Analyze a workout video using the AI pipeline.
    
    This function:
    1. Opens the video file with OpenCV
    2. Processes each frame with MediaPipe Holistic
    3. Extracts pose features and builds sequences
    4. Runs LSTM model predictions
    5. AUTO-DETECTS the exercise type from predictions
    6. Checks form and records mistakes
    7. Generates a comprehensive report
    
    Args:
        file_path: Absolute path to the video file on disk
        user_id: UUID string of the authenticated user
        session_name: Human-readable session name
        model: Loaded TensorFlow Keras model
        labels: Numpy array of class labels
        
    Returns:
        Dict containing:
            - session_id: UUID of the session
            - report: Complete report from ReportGenerator
            - metrics: Key metrics (form_score, performance_rating, etc.)
            
    Raises:
        ValueError: If video cannot be opened or no pose detected
        Exception: If analysis fails
    """
    # Generate unique session ID
    session_id = str(uuid.uuid4())
    logger.info(f"Starting analysis for session {session_id}")
    
    # Initialize session tracker (exercise type will be auto-detected)
    tracker = SessionTracker(session_id=session_id, user_id=user_id)
    tracker.start_session(session_name=session_name)
    start_time = datetime.now()
    
    # Initialize feature buffer (deque automatically removes oldest when full)
    feature_buffer = deque(maxlen=50)
    
    # Track all predictions to determine dominant exercise type
    all_predictions = []

    # Open video
    cap = cv2.VideoCapture(file_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video file: {file_path}")
    
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Calculate actual video duration from video properties (not processing time)
    actual_video_duration = total_video_frames / video_fps if video_fps > 0 else 0
    
    logger.info(f"Video opened: {total_video_frames} frames at {video_fps} FPS")
    logger.info(f"Actual video duration: {actual_video_duration:.2f} seconds")
    
    # Analysis constants
    CONFIDENCE_THRESHOLD = 0.70
    SEQUENCE_LENGTH = 50
    frame_number = 0
    
    try:
        # Process frames with MediaPipe
        with mp.solutions.holistic.Holistic(
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
            model_complexity=0  # Use 0 for speed
        ) as holistic:
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                frame_number += 1
                # Use the video's own playback time (frame / fps), not wall-clock
                # processing time. Processing a frame (MediaPipe + LSTM inference)
                # takes real time on CPU, so for a short video the wall-clock
                # elapsed time can end up far longer than the video itself,
                # making recorded mistake timestamps (e.g. 00:43) exceed the
                # actual video duration (e.g. 8 seconds).
                timestamp = frame_number / video_fps
                
                # Resize for speed
                frame_small = cv2.resize(frame, (520, 300))
                
                # Convert BGR to RGB
                frame_rgb = cv2.cvtColor(frame_small, cv2.COLOR_BGR2RGB)
                frame_rgb.flags.writeable = False  # Performance optimization
                
                # Process with MediaPipe
                results = holistic.process(frame_rgb)
                frame_rgb.flags.writeable = True
                
                # Increment frame count
                tracker.increment_frame_count()
                
                # Check if pose detected
                if results.pose_landmarks is None:
                    continue
                
                # FIXED: Increment pose count when pose is detected
                tracker.increment_pose_count()
                
                # Extract features
                features = extract_pose_features(results)
                if features is None:
                    continue
                
                # Add to buffer
                feature_buffer.append(features)
                
                # Need full sequence for prediction
                if len(feature_buffer) < SEQUENCE_LENGTH:
                    continue
                
                # Prepare input for model
                input_features = np.array(feature_buffer, dtype=np.float32)
                input_features = input_features.reshape(1, SEQUENCE_LENGTH, -1)
                
                # Run prediction
                try:
                    prediction = model.predict(input_features, verbose=0)
                    idx = int(np.argmax(prediction[0]))
                    confidence = float(np.max(prediction[0]))
                    predicted_class = str(labels[idx])
                except Exception as e:
                    logger.error(f"Prediction error at frame {frame_number}: {e}")
                    continue
                
                # Check confidence threshold
                if confidence < CONFIDENCE_THRESHOLD:
                    continue
                
                # Store prediction for exercise type detection
                all_predictions.append(predicted_class)

                # Get frame dimensions for form checks
                h, w = frame_small.shape[:2]

                # Normalize class name
                cls_normalized = predicted_class.lower().replace(" ", "").replace("-", "_")

                # Run form check based on detected exercise type
                feedback = None
                if "push" in cls_normalized:
                    feedback, _ = check_pushup_form(results, w, h)
                elif "squat" in cls_normalized:
                    feedback, _ = check_squat_form(results, w, h)
                elif "sit" in cls_normalized:
                    feedback, _ = check_situp_form(results, w, h)

                # Record mistake if bad form detected
                if feedback and "Bad Form" in feedback:
                    mistake_type, mistake_message, severity = \
                        MistakeClassifier.classify_feedback(feedback, predicted_class)

                    if mistake_type:
                        tracker.record_mistake(
                            timestamp=timestamp,
                            frame_number=frame_number,
                            exercise_type=predicted_class,
                            mistake_type=mistake_type,
                            mistake_message=mistake_message,
                            severity=severity
                        )

                # Log progress every 100 frames
                if frame_number % 100 == 0:
                    logger.info(f"Processed {frame_number}/{total_video_frames} frames")

    finally:
        # Always release the video capture
        cap.release()
        logger.info(f"Video capture released. Processed {frame_number} frames")

    # Determine the dominant exercise type from all predictions
    if all_predictions:
        # Count occurrences of each exercise type
        prediction_counts = Counter(all_predictions)
        detected_exercise = prediction_counts.most_common(1)[0][0]
        logger.info(f"Detected exercise type: {detected_exercise} (from {len(all_predictions)} predictions)")
        
        # Normalize to standard format
        detected_exercise_normalized = detected_exercise.lower().replace(" ", "_").replace("-", "_")
        if "push" in detected_exercise_normalized:
            exercise_type = "push_up"
        elif "squat" in detected_exercise_normalized:
            exercise_type = "squat"
        elif "sit" in detected_exercise_normalized:
            exercise_type = "sit_up"
        else:
            exercise_type = detected_exercise_normalized
    else:
        # No predictions made - use generic type
        exercise_type = "unknown"
        logger.warning("No exercise predictions made during analysis")
    
    # End session and generate report
    tracker.end_session()
    session_data = tracker.get_session_summary()
    
    # Check if any pose was detected
    total_frames = session_data["total_frames_processed"]
    if total_frames == 0:
        raise ValueError("No pose detected in video. Ensure the full body is visible.")
    
    # Override exercise_detected with our determined type
    session_data["exercise_detected"] = exercise_type
    
    # Override duration with actual video duration (not processing time)
    session_data["duration_seconds"] = actual_video_duration
    
    # Generate report
    report = ReportGenerator.generate_report(session_data)
    
    # Calculate form score
    form_score = calculate_form_score(report, total_frames)
    
    # Extract metrics
    performance_rating = report["overall_summary"]["performance_rating"]
    total_mistakes = report["statistics"]["total_mistakes"]
    duration_seconds = session_data["duration_seconds"]
    
    logger.info(f"Analysis complete: {total_mistakes} mistakes, form score {form_score}, exercise: {exercise_type}")
    
    # Return result
    return {
        "session_id": session_id,
        "report": report,
        "metrics": {
            "form_score": form_score,
            "performance_rating": performance_rating,
            "total_mistakes": total_mistakes,
            "duration_seconds": duration_seconds,
            "total_frames_processed": total_frames,
            "exercise_detected": exercise_type
        }
    }
