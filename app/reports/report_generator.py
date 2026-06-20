"""
Report Generator Module
Generates structured, user-friendly workout session reports.
Includes mistake analysis, injury warnings, and correction tips.
"""
from typing import Dict, List, Optional
from datetime import datetime
from collections import defaultdict
from app.reports.mistake_classifier import MistakeClassifier


class ReportGenerator:
    """
    Generates comprehensive session reports from tracked data.

    This module takes SessionTracker data and produces a structured,
    user-friendly report suitable for frontend display or API response.
    """

    # Thresholds for warnings
    HIGH_FREQUENCY_THRESHOLD = 5  # Mistakes repeated 5+ times trigger warning
    CRITICAL_FREQUENCY_THRESHOLD = 10  # Mistakes repeated 10+ times are critical

    @staticmethod
    def format_timestamp(seconds: float) -> str:
        """Convert seconds to MM:SS format."""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"

    @staticmethod
    def generate_injury_warning(mistake_type: str, count: int) -> Dict[str, str]:
        """
        Generate a friendly injury risk warning for repeated mistakes.

        Args:
            mistake_type: The type of mistake
            count: Number of times it occurred

        Returns:
            Dictionary with warning level and message
        """
        injury_risk = MistakeClassifier.get_injury_risk(mistake_type)
        is_high_risk = MistakeClassifier.is_high_risk_mistake(mistake_type)

        # Determine warning level
        if count >= ReportGenerator.CRITICAL_FREQUENCY_THRESHOLD:
            level = "critical"
            frequency_text = "very frequently"
        elif count >= ReportGenerator.HIGH_FREQUENCY_THRESHOLD:
            level = "warning"
            frequency_text = "several times"
        else:
            level = "info"
            frequency_text = "a few times"

        # Craft friendly message
        if is_high_risk and count >= ReportGenerator.HIGH_FREQUENCY_THRESHOLD:
            message = (
                f"This movement pattern happened {frequency_text} during your session. "
                f"Over time, it may place extra stress on your body and could lead to {injury_risk}. "
                f"We recommend focusing on the correction tips below to protect yourself."
            )
        elif count >= ReportGenerator.HIGH_FREQUENCY_THRESHOLD:
            message = (
                f"We noticed this pattern {frequency_text} in your workout. "
                f"While not immediately harmful, repeated occurrences could contribute to {injury_risk}. "
                f"Try to be mindful of this in your next session."
            )
        else:
            message = (
                f"This happened {frequency_text} during your session. "
                f"Keep an eye on it to prevent {injury_risk}."
            )

        return {
            "level": level,
            "message": message,
            "injury_risk": injury_risk
        }

    @classmethod
    def generate_mistake_summary(cls, session_data: dict) -> List[Dict]:
        """
        Generate a summary of all mistakes with aggregation and warnings.

        Args:
            session_data: Session summary from SessionTracker

        Returns:
            List of mistake summaries with metadata
        """
        mistake_frequency = session_data.get("mistake_frequency", {})
        mistakes_by_type = defaultdict(list)

        # Group mistakes by type
        for mistake in session_data.get("mistakes", []):
            mistakes_by_type[mistake["mistake_type"]].append(mistake)

        summaries = []

        for mistake_type, occurrences in mistakes_by_type.items():
            count = len(occurrences)

            # Get first and last occurrence
            first_occurrence = occurrences[0]
            last_occurrence = occurrences[-1]

            # Get all timestamps
            timestamps = [m["timestamp"] for m in occurrences]

            # Get correction tip
            correction = MistakeClassifier.get_correction_tip(mistake_type)

            # Generate warning if high frequency
            warning = None
            if count >= cls.HIGH_FREQUENCY_THRESHOLD:
                warning = cls.generate_injury_warning(mistake_type, count)

            summary = {
                "mistake_type": mistake_type,
                "mistake_message": first_occurrence["mistake_message"],
                "count": count,
                "first_seen_at": cls.format_timestamp(first_occurrence["timestamp"]),
                "last_seen_at": cls.format_timestamp(last_occurrence["timestamp"]),
                "timestamps": [cls.format_timestamp(t) for t in timestamps],
                "severity": first_occurrence["severity"],
                "correction_tip": correction,
                "warning": warning
            }

            summaries.append(summary)

        # Sort by count (most frequent first)
        summaries.sort(key=lambda x: x["count"], reverse=True)

        return summaries

    @classmethod
    def generate_overall_summary(cls, session_data: dict, mistake_summaries: List[Dict]) -> Dict:
        """
        Generate overall session summary with key insights.

        Args:
            session_data: Session summary from SessionTracker
            mistake_summaries: Processed mistake summaries

        Returns:
            Dictionary with overall insights
        """
        total_mistakes = session_data.get("total_mistakes", 0)
        duration = session_data.get("duration_seconds", 0)
        exercise = session_data.get("exercise_detected", "Unknown")

        # Calculate statistics
        unique_mistake_types = len(mistake_summaries)
        high_risk_count = sum(1 for m in mistake_summaries if m.get("warning"))

        # Determine overall performance
        if total_mistakes == 0:
            performance = "excellent"
            message = "Outstanding! You maintained excellent form throughout your entire session. Keep up the great work!"
        elif total_mistakes <= 3:
            performance = "good"
            message = "Great job! You had only a few form breaks. Focus on the tips below to perfect your technique."
        elif total_mistakes <= 10:
            performance = "fair"
            message = "Good effort! There's room for improvement in your form. Review the corrections below for your next session."
        else:
            performance = "needs_improvement"
            message = "We noticed several form issues during your workout. Don't worry - form takes practice! Focus on the key corrections below."

        # Add injury risk note if applicable
        if high_risk_count > 0:
            message += f" Please pay special attention to the {high_risk_count} warning(s) below to prevent potential injury."

        return {
            "performance_rating": performance,
            "message": message,
            "total_mistakes": total_mistakes,
            "unique_mistake_types": unique_mistake_types,
            "high_risk_warnings": high_risk_count,
            "duration_formatted": cls.format_timestamp(duration),
            "exercise_type": exercise
        }

    @classmethod
    def generate_report(cls, session_data: dict) -> Dict:
        """
        Generate complete session report.

        Args:
            session_data: Session summary from SessionTracker.get_session_summary()

        Returns:
            Complete structured report ready for JSON serialization
        """
        # Check if no pose was detected throughout the session
        frames_with_pose = session_data.get("frames_with_pose", 0)
        total_frames = session_data.get("total_frames_processed", 0)
        
        # If no poses detected or very few poses (less than 10% of frames)
        if frames_with_pose == 0 or (total_frames > 0 and frames_with_pose < total_frames * 0.1):
            return cls.generate_no_pose_report(session_data)
        
        # Generate mistake summaries
        mistake_summaries = cls.generate_mistake_summary(session_data)

        # Generate overall summary
        overall_summary = cls.generate_overall_summary(session_data, mistake_summaries)

        # Build complete report
        report = {
            "session_info": {
                "session_id": session_data.get("session_id"),
                "user_id": session_data.get("user_id"),
                "session_name": session_data.get("session_name"),
                "start_time": session_data.get("start_time"),
                "end_time": session_data.get("end_time"),
                "duration_seconds": session_data.get("duration_seconds"),
                "duration_formatted": cls.format_timestamp(session_data.get("duration_seconds", 0)),
                "exercise_detected": session_data.get("exercise_detected"),
                "total_frames_processed": session_data.get("total_frames_processed")
            },
            "overall_summary": overall_summary,
            "mistakes": mistake_summaries,
            "statistics": {
                "total_mistakes": session_data.get("total_mistakes", 0),
                "unique_mistake_types": len(mistake_summaries),
                "most_common_mistake": mistake_summaries[0]["mistake_type"] if mistake_summaries else None,
                "high_frequency_mistakes": session_data.get("high_frequency_mistakes", [])
            },
            "generated_at": datetime.now().isoformat()
        }

        return report

    @classmethod
    def generate_no_pose_report(cls, session_data: dict) -> Dict:
        """
        Generate a special report when no pose was detected during the session.
        
        This happens when the user was not in the camera frame or too far away.
        
        Args:
            session_data: Session summary from SessionTracker
            
        Returns:
            Special "no pose detected" report
        """
        return {
            "session_info": {
                "session_id": session_data.get("session_id"),
                "user_id": session_data.get("user_id"),
                "session_name": session_data.get("session_name"),
                "start_time": session_data.get("start_time"),
                "end_time": session_data.get("end_time"),
                "duration_seconds": session_data.get("duration_seconds"),
                "duration_formatted": cls.format_timestamp(session_data.get("duration_seconds", 0)),
                "exercise_detected": None,
                "total_frames_processed": session_data.get("total_frames_processed")
            },
            "overall_summary": {
                "performance_rating": "no_pose_detected",
                "message": (
                    "We couldn't detect your body in the camera frame during this session. "
                    "For the best results, please make sure you're standing where your full body is visible "
                    "in the camera. Try standing a bit further back so we can see you from head to toe!"
                ),
                "total_mistakes": 0,
                "unique_mistake_types": 0,
                "high_risk_warnings": 0,
                "duration_formatted": cls.format_timestamp(session_data.get("duration_seconds", 0)),
                "exercise_type": None
            },
            "mistakes": [],
            "statistics": {
                "total_mistakes": 0,
                "unique_mistake_types": 0,
                "most_common_mistake": None,
                "high_frequency_mistakes": []
            },
            "generated_at": datetime.now().isoformat(),
            "no_pose_detected": True  # Flag for frontend to handle differently
        }
    
    @classmethod
    def generate_quick_summary(cls, session_data: dict) -> str:
        """
        Generate a quick text summary for display.

        Args:
            session_data: Session summary from SessionTracker

        Returns:
            Human-readable summary string
        """
        total_mistakes = session_data.get("total_mistakes", 0)
        exercise = session_data.get("exercise_detected", "workout")
        duration = cls.format_timestamp(session_data.get("duration_seconds", 0))

        if total_mistakes == 0:
            return f"Perfect {exercise} session! Duration: {duration}. No form issues detected. Excellent work!"
        else:
            unique_types = len(set(m["mistake_type"] for m in session_data.get("mistakes", [])))
            return f"{exercise.title()} session completed in {duration}. Detected {total_mistakes} form issue(s) across {unique_types} category(ies). Check your detailed report for improvement tips."
