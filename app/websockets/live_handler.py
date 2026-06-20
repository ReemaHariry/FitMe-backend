"""
Live Training WebSocket Handler

This is where the real-time AI magic happens.
Processes live video frames and provides instant feedback.

CRITICAL REQUIREMENTS:
- Only ONE feature_buffer per session (stored in session_service)
- model.predict is CPU-bound — wrap in run_in_executor
- Never crash on a single bad frame — always catch exceptions
- Send a response for EVERY frame received (even if just a status)
- Handle WebSocketDisconnect gracefully
"""

import json
import base64
import asyncio
import logging
import numpy as np
import cv2
import mediapipe as mp
from collections import deque
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect

from app.services.session_service import (
    get_live_session,
    get_tracker,
    update_last_activity
)
from app.ai.pose_utils import extract_pose_features
from app.ai.form_checks import (
    check_pushup_form,
    check_squat_form,
    check_situp_form
)
from app.reports.mistake_classifier import MistakeClassifier

logger = logging.getLogger(__name__)

SEQUENCE_LENGTH = 50
CONFIDENCE_THRESHOLD = 0.70


async def handle_live_session(websocket: WebSocket, session_id: str):
    """
    Main WebSocket handler for a live training session.

    Called by the WebSocket route in main.py.
    Runs for the entire duration of the session.
    Exits when client disconnects or session ends.

    Args:
        websocket: FastAPI WebSocket connection
        session_id: UUID of the session
    """
    await websocket.accept()
    logger.info(f"WebSocket connected: session {session_id}")

    # Get model from app state
    model = websocket.app.state.model
    labels = websocket.app.state.labels
    model_loaded = websocket.app.state.model_loaded

    # Get the session from memory
    session = get_live_session(session_id)
    if not session:
        await websocket.send_json({
            "error": "Session not found. Start a session first.",
            "status": "error"
        })
        await websocket.close()
        return

    if not model_loaded:
        await websocket.send_json({
            "error": "AI model not available.",
            "status": "error"
        })
        await websocket.close()
        return

    tracker = session["tracker"]

    # Initialize feature buffer for this session
    # Store it in the session dict so it persists across frames
    feature_buffer = deque(maxlen=SEQUENCE_LENGTH)
    session["feature_buffer"] = feature_buffer

    frame_id = 0

    try:
        with mp.solutions.holistic.Holistic(
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
            model_complexity=0
        ) as holistic:

            while True:
                try:
                    # Receive message from React
                    raw_message = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=10.0
                    )
                except asyncio.TimeoutError:
                    # No frame received for 10 seconds — send keepalive
                    await websocket.send_json({"type": "keepalive"})
                    continue

                # Parse the incoming JSON
                try:
                    message = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue

                # Handle ping messages from React
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue

                frame_id += 1
                client_timestamp = message.get("timestamp", 0.0)
                frame_b64 = message.get("frame", "")

                update_last_activity(session_id)

                # Process the frame
                result = await process_single_frame(
                    frame_b64=frame_b64,
                    holistic=holistic,
                    feature_buffer=feature_buffer,
                    model=model,
                    labels=labels,
                    tracker=tracker,
                    frame_id=frame_id,
                    timestamp=client_timestamp
                )

                result["frame_id"] = frame_id
                result["total_mistakes_so_far"] = tracker.get_mistake_count()

                await websocket.send_json(result)

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: session {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error for session {session_id}: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "error": str(e),
                "status": "error"
            })
        except Exception:
            pass
    finally:
        logger.info(f"WebSocket handler finished: session {session_id}")


async def process_single_frame(
    frame_b64: str,
    holistic,
    feature_buffer: deque,
    model,
    labels: np.ndarray,
    tracker,
    frame_id: int,
    timestamp: float
) -> dict:
    """
    Processes one video frame and returns feedback.

    This function is async but calls sync CPU functions
    via run_in_executor for the heavy work.

    Args:
        frame_b64: Base64 encoded JPEG frame
        holistic: MediaPipe Holistic instance
        feature_buffer: Deque for storing frame features
        model: Loaded Keras model
        labels: Exercise class labels
        tracker: SessionTracker instance
        frame_id: Current frame number
        timestamp: Timestamp from client (seconds)

    Returns:
        Dict that gets sent back to React as JSON
    """
    try:
        # Decode base64 frame to numpy array
        if "," in frame_b64:
            frame_b64 = frame_b64.split(",")[1]

        frame_bytes = base64.b64decode(frame_b64)
        nparr = np.frombuffer(frame_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return {
                "status": "waiting",
                "feedback": "Cannot read frame",
                "buffer_progress": len(feature_buffer)
            }

        # Resize for speed (same as video_service.py)
        frame_small = cv2.resize(frame, (520, 300))
        frame_rgb = cv2.cvtColor(frame_small, cv2.COLOR_BGR2RGB)
        frame_rgb.flags.writeable = False

        # Run MediaPipe — sync but fast
        results = holistic.process(frame_rgb)
        frame_rgb.flags.writeable = True

        tracker.increment_frame_count()

        # No pose detected
        if results.pose_landmarks is None:
            return {
                "status": "waiting",
                "feedback": "Position yourself so your full body is visible",
                "buffer_progress": len(feature_buffer),
                "form_status": "none"
            }

        # Extract landmarks
        features = extract_pose_features(results)
        if features is None:
            return {
                "status": "waiting",
                "feedback": "Detecting pose...",
                "buffer_progress": len(feature_buffer),
                "form_status": "none"
            }

        # Pose detected successfully - increment counter
        tracker.increment_pose_count()

        feature_buffer.append(features)
        buffer_size = len(feature_buffer)

        # Buffer not full yet — cannot predict
        if buffer_size < SEQUENCE_LENGTH:
            return {
                "status": "buffering",
                "feedback": f"Detecting exercise... ({buffer_size}/{SEQUENCE_LENGTH})",
                "buffer_progress": buffer_size,
                "form_status": "none",
                "exercise": None,
                "confidence": None
            }

        # Run LSTM prediction in thread executor (CPU-bound)
        input_features = np.array(feature_buffer, dtype=np.float32)
        input_features = input_features.reshape(1, SEQUENCE_LENGTH, -1)

        loop = asyncio.get_event_loop()
        prediction = await loop.run_in_executor(
            None,
            lambda: model.predict(input_features, verbose=0)
        )

        idx = int(np.argmax(prediction[0]))
        confidence = float(np.max(prediction[0]))
        predicted_class = str(labels[idx])

        # Confidence too low — do not trust prediction
        if confidence < CONFIDENCE_THRESHOLD:
            return {
                "status": "analyzing",
                "feedback": "Tracking movement...",
                "exercise": predicted_class,
                "confidence": confidence,
                "form_status": "none",
                "buffer_progress": SEQUENCE_LENGTH
            }

        # Run form check for the detected exercise
        h, w = frame_small.shape[:2]
        cls_normalized = (
            predicted_class.lower()
            .replace(" ", "")
            .replace("-", "_")
        )

        feedback = None
        metrics = {}

        if "push" in cls_normalized:
            feedback, metrics = check_pushup_form(results, w, h)
        elif "squat" in cls_normalized:
            feedback, metrics = check_squat_form(results, w, h)
        elif "sit" in cls_normalized:
            feedback, metrics = check_situp_form(results, w, h)

        if feedback is None:
            feedback = "Good form!"

        form_status = "good" if "Good Form" in feedback else "bad"
        feedback_text = feedback.replace("Bad Form: ", "").replace("Good Form", "Good form!")

        mistakes_this_frame = []

        # Record mistake if bad form detected
        if form_status == "bad":
            mistake_type, mistake_message, severity = MistakeClassifier.classify_feedback(
                feedback,
                predicted_class
            )

            if mistake_type:
                was_recorded = tracker.record_mistake(
                    timestamp=timestamp,
                    frame_number=frame_id,
                    exercise_type=predicted_class,
                    mistake_type=mistake_type,
                    mistake_message=mistake_message,
                    severity=severity
                )
                if was_recorded:
                    mistakes_this_frame.append(mistake_message)

        return {
            "status": "analyzing",
            "exercise": predicted_class,
            "confidence": round(confidence, 3),
            "form_status": form_status,
            "feedback": feedback_text,
            "mistakes_this_frame": mistakes_this_frame,
            "buffer_progress": SEQUENCE_LENGTH,
            "metrics": metrics
        }

    except Exception as e:
        logger.error(f"Frame processing error (frame {frame_id}): {e}")
        return {
            "status": "error",
            "feedback": "Frame processing error",
            "buffer_progress": len(feature_buffer),
            "form_status": "none",
            "error": str(e)
        }
