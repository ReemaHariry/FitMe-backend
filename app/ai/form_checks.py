# form_checks.py
import numpy as np
import mediapipe as mp

mp_pose = mp.solutions.pose


def calculate_angle(a, b, c):
    """
    Angle ABC in degrees using 2D points a,b,c (x,y).
    """
    a = np.array(a, dtype=np.float32)
    b = np.array(b, dtype=np.float32)
    c = np.array(c, dtype=np.float32)

    ba = a - b
    bc = c - b

    denom = (np.linalg.norm(ba) * np.linalg.norm(bc))
    if denom == 0:
        return 0.0

    cosang = np.dot(ba, bc) / denom
    cosang = np.clip(cosang, -1.0, 1.0)
    return float(np.degrees(np.arccos(cosang)))


def _xy(landmarks, idx, w, h):
    lm = landmarks[idx]
    return (lm.x * w, lm.y * h)


def check_pushup_form(results, w, h):
    """
    Simple push-up rules:
    - back straightness ~ shoulder-hip-knee close to 180
    - elbow angle sanity range
    """
    L = mp_pose.PoseLandmark
    lms = results.pose_landmarks.landmark

    sh = _xy(lms, L.LEFT_SHOULDER.value, w, h)
    hip = _xy(lms, L.LEFT_HIP.value, w, h)
    knee = _xy(lms, L.LEFT_KNEE.value, w, h)

    elb = _xy(lms, L.LEFT_ELBOW.value, w, h)
    wri = _xy(lms, L.LEFT_WRIST.value, w, h)

    back_angle = calculate_angle(sh, hip, knee)
    elbow_angle = calculate_angle(sh, elb, wri)

    issues = []
    if back_angle < 160:
        issues.append("Straighten your back")

    if elbow_angle > 170:
        issues.append("Bend elbows more (too straight)")
    if elbow_angle < 40:
        issues.append("Don't go too low (elbow too closed)")

    feedback = "Good Form" if not issues else "Bad Form: " + " | ".join(issues)
    metrics = {"back_angle": back_angle, "elbow_angle": elbow_angle}
    return feedback, metrics


def check_squat_form(results, w, h):
    """
    Improved squat form checks (focus: back posture).

    Back posture method:
    1) Torso Lean Angle (hip->shoulder vs vertical):
       - small = upright
       - large = leaning forward too much

    2) Rounded-back proxy:
       - large shoulder-hip horizontal drift suggests collapsing/rounding (approximation)

    Also:
    - knee past toes check (2D proxy)
    - knee angle for depth stability

    Returns: (feedback_string, metrics_dict)
    """
    L = mp_pose.PoseLandmark
    lms = results.pose_landmarks.landmark

    def xy(idx):
        lm = lms[idx]
        return (lm.x * w, lm.y * h)

    # Use both sides and average (more stable)
    sh_L = xy(L.LEFT_SHOULDER.value)
    hip_L = xy(L.LEFT_HIP.value)
    knee_L = xy(L.LEFT_KNEE.value)
    ankle_L = xy(L.LEFT_ANKLE.value)
    toe_L = xy(L.LEFT_FOOT_INDEX.value)

    sh_R = xy(L.RIGHT_SHOULDER.value)
    hip_R = xy(L.RIGHT_HIP.value)
    knee_R = xy(L.RIGHT_KNEE.value)
    ankle_R = xy(L.RIGHT_ANKLE.value)
    toe_R = xy(L.RIGHT_FOOT_INDEX.value)

    shoulder = ((sh_L[0] + sh_R[0]) / 2, (sh_L[1] + sh_R[1]) / 2)
    hip = ((hip_L[0] + hip_R[0]) / 2, (hip_L[1] + hip_R[1]) / 2)
    knee = ((knee_L[0] + knee_R[0]) / 2, (knee_L[1] + knee_R[1]) / 2)
    ankle = ((ankle_L[0] + ankle_R[0]) / 2, (ankle_L[1] + ankle_R[1]) / 2)
    toe = ((toe_L[0] + toe_R[0]) / 2, (toe_L[1] + toe_R[1]) / 2)

    # Knee angle (hip-knee-ankle) = depth/position
    knee_angle = calculate_angle(hip, knee, ankle)

    # Torso lean relative to vertical:
    # vector hip -> shoulder
    vx = shoulder[0] - hip[0]
    vy = shoulder[1] - hip[1]
    eps = 1e-6
    torso_lean_deg = float(np.degrees(np.arctan2(abs(vx), abs(vy) + eps)))  # 0..90

    # Rounded-back proxy: shoulder-hip horizontal offset too large
    shoulder_hip_dx = shoulder[0] - hip[0]  # + means shoulders forward
    rounded_back_flag = abs(shoulder_hip_dx) > 120  # tune 90..150 if needed

    # Knee past toes proxy (x position)
    knee_past_toe = (knee[0] - toe[0]) > 25  # tune 15..40 if needed

    issues = []

    # Back posture rules (main)
    # For a basic demo: too much forward lean
    if torso_lean_deg > 55:  # tune 50..60
        issues.append("Keep chest up (too much forward lean)")

    if rounded_back_flag:
        issues.append("Avoid rounding (keep back neutral)")

    # Knee tracking
    if knee_past_toe and knee_angle < 150:
        issues.append("Knees too far past toes")

    # Depth stability
    if knee_angle < 55:
        issues.append("Control depth (too deep/unstable)")

    feedback = "Good Form" if not issues else "Bad Form: " + " | ".join(issues)
    metrics = {
        "knee_angle": knee_angle,
        "torso_lean_deg": torso_lean_deg,
        "shoulder_hip_dx": shoulder_hip_dx,
        "knee_past_toe": knee_past_toe,
    }
    return feedback, metrics


def check_situp_form(results, w, h):
    """
    Simple sit-up starter rules (you can refine later):
    - torso angle proxy (shoulder-hip-knee)
    - neck-forward proxy (nose x far from shoulder x)
    """
    L = mp_pose.PoseLandmark
    lms = results.pose_landmarks.landmark

    sh = _xy(lms, L.LEFT_SHOULDER.value, w, h)
    hip = _xy(lms, L.LEFT_HIP.value, w, h)
    knee = _xy(lms, L.LEFT_KNEE.value, w, h)
    nose = _xy(lms, L.NOSE.value, w, h)

    torso_angle = calculate_angle(sh, hip, knee)
    neck_forward = abs(nose[0] - sh[0]) > 80  # tune based on camera distance

    issues = []
    if torso_angle > 165:
        issues.append("Curl up more (not enough range)")
    if neck_forward:
        issues.append("Don't pull your neck forward")

    feedback = "Good Form" if not issues else "Bad Form: " + " | ".join(issues)
    metrics = {"torso_angle": torso_angle, "neck_forward": neck_forward}
    return feedback, metrics
