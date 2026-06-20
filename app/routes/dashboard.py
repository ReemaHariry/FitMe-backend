"""
Dashboard Routes

Provides aggregate statistics and chart data for the dashboard.
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timedelta, date
import logging
from collections import defaultdict
from app.services.supabase_service import get_supabase_client
from app.routes.users import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/stats")
async def get_dashboard_stats(current_user: dict = Depends(get_current_user)):
    """
    Returns aggregate statistics for the dashboard stat cards.
    All calculations happen from the exercise_sessions table.
    """
    user_id = current_user["id"]
    
    try:
        supabase = get_supabase_client()
        
        # FIXED: Add detailed logging
        logger.info(f"Fetching dashboard stats for user: {user_id}")
        
        # Fetch all completed sessions for this user
        result = supabase.table("exercise_sessions").select(
            "id, exercise_type, duration_seconds, form_score, status, started_at, created_at"
        ).eq("user_id", user_id).eq("status", "completed").order("created_at", desc=False).execute()
        
        sessions = result.data or []
        
        # FIXED: Log the raw data to diagnose
        logger.info(f"Found {len(sessions)} completed sessions")
        if sessions:
            logger.info(f"First session sample: {sessions[0]}")
            logger.info(f"Duration values: {[s.get('duration_seconds') for s in sessions[:3]]}")
        
        if not sessions:
            return {
                "total_sessions": 0,
                "completed_sessions": 0,
                "total_minutes": 0,
                "average_form_score": 0,
                "current_streak": 0,
                "best_streak": 0,
                "most_practiced_exercise": "none",
                "sessions_this_week": 0,
                "improvement_this_month": 0,
                "best_score": 0,  # NEW
                "best_score_exercise": "none",  # NEW
                "active_dates_last_30": []  # NEW
            }
        
        # Total sessions and minutes
        total_sessions = len(sessions)
        # FIXED: Handle None and 0 values more robustly
        total_seconds = sum(float(s.get("duration_seconds") or 0) for s in sessions if s.get("duration_seconds") is not None)
        total_minutes = round(total_seconds / 60)
        
        # Average form score (only from sessions with scores)
        scored = [s["form_score"] for s in sessions if s.get("form_score") is not None]
        average_form_score = round(sum(scored) / len(scored)) if scored else 0
        
        # NEW: Best score and exercise
        best_score = max(scored) if scored else 0
        best_score_session = max(sessions, key=lambda s: s.get("form_score") or 0) if sessions else None
        best_score_exercise = best_score_session.get("exercise_type", "none") if best_score_session else "none"
        
        # Most practiced exercise
        exercise_counts = defaultdict(int)
        for s in sessions:
            if s.get("exercise_type"):
                exercise_counts[s["exercise_type"]] += 1
        most_practiced = max(exercise_counts, key=exercise_counts.get) if exercise_counts else "none"
        
        # Sessions this week (Monday to today) - use proper date comparison
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        sessions_this_week = 0
        for s in sessions:
            raw = s.get("created_at") or ""
            try:
                s_date = date.fromisoformat(raw[:10])
                if s_date >= monday:
                    sessions_this_week += 1
            except Exception:
                pass
        
        # Build set of dates that had sessions
        session_dates = set()
        for s in sessions:
            raw = s.get("created_at") or s.get("started_at")
            if raw:
                try:
                    session_dates.add(raw[:10])  # YYYY-MM-DD
                except Exception:
                    pass
        
        # Current streak: consecutive days ending today or yesterday
        current_streak = 0
        check_date = today
        # If no session today, start check from yesterday
        if today.isoformat() not in session_dates:
            check_date = today - timedelta(days=1)
        while check_date.isoformat() in session_dates:
            current_streak += 1
            check_date -= timedelta(days=1)
        
        # Best streak: find the longest consecutive run in history
        best_streak = 0
        if session_dates:
            sorted_dates = sorted(session_dates)
            run = 1
            for i in range(1, len(sorted_dates)):
                prev = date.fromisoformat(sorted_dates[i - 1])
                curr = date.fromisoformat(sorted_dates[i])
                if (curr - prev).days == 1:
                    run += 1
                    best_streak = max(best_streak, run)
                else:
                    run = 1
            best_streak = max(best_streak, run, current_streak)
        
        # Improvement this month vs last month
        current_month = today.strftime("%Y-%m")
        last_month_date = today.replace(day=1) - timedelta(days=1)
        last_month = last_month_date.strftime("%Y-%m")
        
        this_month_scores = [s["form_score"] for s in sessions 
                            if s.get("form_score") is not None 
                            and s.get("created_at", "")[:7] == current_month]
        last_month_scores = [s["form_score"] for s in sessions 
                            if s.get("form_score") is not None 
                            and s.get("created_at", "")[:7] == last_month]
        
        if this_month_scores and last_month_scores:
            improvement = round(sum(this_month_scores)/len(this_month_scores) - 
                              sum(last_month_scores)/len(last_month_scores))
        else:
            improvement = 0
        
        # NEW: Active dates in last 30 days for streak calendar
        thirty_days_ago = (today - timedelta(days=30)).isoformat()
        active_dates_last_30 = sorted(list(session_dates & {
            (today - timedelta(days=i)).isoformat() for i in range(31)
        }))
        
        return {
            "total_sessions": total_sessions,
            "completed_sessions": total_sessions,
            "total_minutes": total_minutes,
            "average_form_score": average_form_score,
            "current_streak": current_streak,
            "best_streak": best_streak,
            "most_practiced_exercise": most_practiced,
            "sessions_this_week": sessions_this_week,
            "improvement_this_month": improvement,
            "best_score": best_score,  # NEW
            "best_score_exercise": best_score_exercise,  # NEW
            "active_dates_last_30": active_dates_last_30  # NEW
        }
        
    except Exception as e:
        logger.error(f"Dashboard stats error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to load dashboard statistics")


@router.get("/weekly-activity")
async def get_weekly_activity(
    week_offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    """
    Returns minutes exercised per day for a given week.
    week_offset=0 is current week, 1 is last week, etc.
    """
    user_id = current_user["id"]
    
    try:
        supabase = get_supabase_client()
        today = date.today()
        monday = today - timedelta(days=today.weekday()) - timedelta(weeks=week_offset)
        sunday = monday + timedelta(days=6)
        
        # FIXED: Add detailed logging
        logger.info(f"Fetching weekly activity for user {user_id}, week: {monday} to {sunday}")
        
        # FIXED: Fetch sessions in this week with timezone-safe date comparison
        result = supabase.table("exercise_sessions").select(
            "duration_seconds, started_at, created_at"
        ).eq("user_id", user_id).eq("status", "completed").gte(
            "created_at", f"{monday.isoformat()}T00:00:00"
        ).lte("created_at", f"{sunday.isoformat()}T23:59:59").execute()
        
        sessions = result.data or []
        
        # FIXED: Log the raw data
        logger.info(f"Found {len(sessions)} sessions in this week")
        if sessions:
            logger.info(f"Sample session: {sessions[0]}")
            logger.info(f"Duration values: {[s.get('duration_seconds') for s in sessions]}")
        
        # Build day buckets
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        days = []
        
        for i in range(7):
            day_date = monday + timedelta(days=i)
            day_str = day_date.isoformat()
            day_sessions = [s for s in sessions if s.get("created_at", "")[:10] == day_str]
            # FIXED: Handle None and 0 values, ensure non-negative
            minutes = max(0, round(sum(float(s.get("duration_seconds") or 0) for s in day_sessions) / 60))
            days.append({
                "day": day_names[i],
                "date": day_str,
                "minutes": minutes,
                "sessions": len(day_sessions)
            })
        
        total_minutes = sum(d["minutes"] for d in days)
        active_days = [d for d in days if d["minutes"] > 0]
        avg_minutes = round(total_minutes / len(active_days)) if active_days else 0
        
        return {
            "week_start": monday.isoformat(),
            "week_end": sunday.isoformat(),
            "days": days,
            "total_minutes": total_minutes,
            "average_minutes_per_active_day": avg_minutes,
            "active_days": len(active_days)
        }
        
    except Exception as e:
        logger.error(f"Weekly activity error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to load weekly activity")


@router.get("/progress")
async def get_progress(
    months: int = 6,
    current_user: dict = Depends(get_current_user)
):
    """
    Returns average form score per month for the last N months.
    Used for the Progress Over Time line chart.
    """
    user_id = current_user["id"]
    
    try:
        supabase = get_supabase_client()
        today = date.today()
        month_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        
        # Build list of months to query (oldest first)
        target_months = []
        for i in range(months - 1, -1, -1):
            # Go back i months from current month
            month_date = today.replace(day=1)
            for _ in range(i):
                month_date = (month_date - timedelta(days=1)).replace(day=1)
            target_months.append((month_date.year, month_date.month))
        
        # Fetch all scored sessions in the date range
        oldest = target_months[0]
        oldest_str = f"{oldest[0]:04d}-{oldest[1]:02d}-01"
        
        # FIXED: Fetch all sessions with form_score (not null)
        # Note: Supabase Python client uses is_() for NULL checks
        result = supabase.table("exercise_sessions").select(
            "form_score, created_at"
        ).eq("user_id", user_id).eq("status", "completed").gte(
            "created_at", oldest_str
        ).execute()
        
        # FIXED: Filter out null scores in Python instead of in query
        sessions = [s for s in (result.data or []) if s.get("form_score") is not None]
        
        logger.info(f"Found {len(sessions)} sessions with form_score in date range")
        
        # Group by month
        monthly_data = []
        for year, month in target_months:
            month_str = f"{year:04d}-{month:02d}"
            month_sessions = [s for s in sessions if s.get("created_at", "")[:7] == month_str]
            
            if month_sessions:
                scores = [s["form_score"] for s in month_sessions if s.get("form_score")]
                avg_score = round(sum(scores) / len(scores)) if scores else None
            else:
                avg_score = None  # null = no dot on chart
            
            monthly_data.append({
                "month": month_labels[month - 1],
                "year": year,
                "avg_score": avg_score,
                "sessions": len(month_sessions)
            })
        
        # Filter to only months with data for meaningful display
        months_with_data = [m for m in monthly_data if m["avg_score"] is not None]
        current_score = months_with_data[-1]["avg_score"] if months_with_data else 0
        
        if len(months_with_data) >= 2:
            improvement = current_score - months_with_data[0]["avg_score"]
        else:
            improvement = 0
        
        return {
            "months": monthly_data,
            "current_score": current_score,
            "improvement": improvement,
            "total_months_active": len(months_with_data)
        }
        
    except Exception as e:
        logger.error(f"Progress data error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to load progress data")
