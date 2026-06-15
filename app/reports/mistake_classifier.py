"""
Mistake Classifier Module
Converts raw form check feedback into structured mistake events.
Maps feedback strings to categorized mistake types with metadata.
"""
from typing import Tuple, Optional


class MistakeClassifier:
    """
    Classifies and categorizes form feedback into structured mistake types.
    
    This module bridges the gap between form_checks.py output and session_tracker.py input.
    """
    
    # Mistake type mappings with metadata
    MISTAKE_CATALOG = {
        # Push-up mistakes
        "back_not_straight": {
            "keywords": ["straighten your back", "back"],
            "exercise": "push_up",
            "severity": "high",
            "injury_risk": "lower back strain",
            "correction": "Keep your core engaged and maintain a straight line from head to heels. Imagine a plank position throughout the movement."
        },
        "elbows_too_straight": {
            "keywords": ["bend elbows more", "too straight"],
            "exercise": "push_up",
            "severity": "medium",
            "injury_risk": "elbow joint stress",
            "correction": "Bend your elbows to at least 90 degrees at the bottom of the movement. This engages your chest and triceps properly."
        },
        "going_too_low": {
            "keywords": ["don't go too low", "elbow too closed"],
            "exercise": "push_up",
            "severity": "medium",
            "injury_risk": "shoulder impingement",
            "correction": "Lower yourself until your elbows reach about 90 degrees, then push back up. Going too low can stress your shoulders."
        },
        
        # Squat mistakes
        "forward_lean": {
            "keywords": ["keep chest up", "forward lean"],
            "exercise": "squat",
            "severity": "high",
            "injury_risk": "lower back and spine stress",
            "correction": "Keep your chest lifted and eyes forward. Imagine a string pulling your chest up toward the ceiling throughout the squat."
        },
        "rounded_back": {
            "keywords": ["avoid rounding", "back neutral"],
            "exercise": "squat",
            "severity": "high",
            "injury_risk": "spinal disc compression",
            "correction": "Maintain a neutral spine by engaging your core. Think about keeping your back flat like a wall is behind you."
        },
        "knees_past_toes": {
            "keywords": ["knees too far past toes"],
            "exercise": "squat",
            "severity": "high",
            "injury_risk": "knee joint strain and patellar stress",
            "correction": "Push your hips back as you descend, keeping your knees aligned over your toes. Think 'sit back' rather than 'sit down'."
        },
        "depth_too_deep": {
            "keywords": ["control depth", "too deep", "unstable"],
            "exercise": "squat",
            "severity": "medium",
            "injury_risk": "knee instability",
            "correction": "Squat to a depth where your thighs are parallel to the ground. Going deeper requires more flexibility and control."
        },
        
        # Sit-up mistakes
        "insufficient_range": {
            "keywords": ["curl up more", "not enough range"],
            "exercise": "sit_up",
            "severity": "low",
            "injury_risk": "reduced effectiveness",
            "correction": "Curl your torso up higher by engaging your abdominal muscles. Focus on bringing your chest toward your knees."
        },
        "neck_strain": {
            "keywords": ["don't pull your neck", "neck forward"],
            "exercise": "sit_up",
            "severity": "high",
            "injury_risk": "cervical spine strain and neck pain",
            "correction": "Keep your neck neutral by placing your hands behind your head lightly. Lead with your chest, not your head."
        }
    }
    
    @classmethod
    def classify_feedback(cls, feedback: str, exercise_type: str) -> Tuple[Optional[str], Optional[str], str]:
        """
        Classify feedback string into a structured mistake type.
        
        Args:
            feedback: Raw feedback string from form_checks.py (e.g., "Bad Form: Knees too far past toes")
            exercise_type: Exercise being performed (e.g., "squat", "push_up", "sit_up")
            
        Returns:
            Tuple of (mistake_type, mistake_message, severity)
            Returns (None, None, "low") if no mistake detected (Good Form)
        """
        # Check if it's good form
        if "Good Form" in feedback:
            return None, None, "low"
        
        # Extract the actual issue from "Bad Form: <issue>"
        if "Bad Form:" in feedback:
            issue_text = feedback.split("Bad Form:", 1)[1].strip()
        else:
            issue_text = feedback
        
        # Normalize exercise type
        exercise_normalized = exercise_type.lower().replace(" ", "_").replace("-", "_")
        
        # Try to match against catalog
        for mistake_type, metadata in cls.MISTAKE_CATALOG.items():
            # Check if this mistake applies to this exercise
            if metadata["exercise"] not in exercise_normalized and exercise_normalized not in metadata["exercise"]:
                continue
            
            # Check if any keyword matches
            for keyword in metadata["keywords"]:
                if keyword.lower() in issue_text.lower():
                    return mistake_type, issue_text, metadata["severity"]
        
        # If no match found, create a generic mistake
        return "form_issue", issue_text, "medium"
    
    @classmethod
    def get_correction_tip(cls, mistake_type: str) -> str:
        """Get the correction tip for a specific mistake type."""
        if mistake_type in cls.MISTAKE_CATALOG:
            return cls.MISTAKE_CATALOG[mistake_type]["correction"]
        return "Focus on maintaining proper form throughout the movement."
    
    @classmethod
    def get_injury_risk(cls, mistake_type: str) -> str:
        """Get the injury risk description for a specific mistake type."""
        if mistake_type in cls.MISTAKE_CATALOG:
            return cls.MISTAKE_CATALOG[mistake_type]["injury_risk"]
        return "potential strain or discomfort"
    
    @classmethod
    def is_high_risk_mistake(cls, mistake_type: str) -> bool:
        """Check if a mistake type is high severity."""
        if mistake_type in cls.MISTAKE_CATALOG:
            return cls.MISTAKE_CATALOG[mistake_type]["severity"] == "high"
        return False
