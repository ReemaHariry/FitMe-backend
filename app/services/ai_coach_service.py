"""
AI Coach Service

A LangChain-powered fitness chatbot built on Groq (Llama 3).

Responsibilities:
- Hold a strong, fitness-only system prompt (the "FitMe AI Coach" persona).
- Automatically pull the logged-in user's profile, sessions and report
  mistakes from Supabase and inject them into the prompt context, so the
  user never has to re-state their age/weight/goal/etc.
- Keep per-user conversation memory so the bot remembers earlier messages.

This module deliberately does NOT touch the exercise classifier, MediaPipe
pipeline, report generation, or database schema. It only READS existing data.
"""

import logging
from typing import Dict, List, Optional

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.chat_history import BaseChatMessageHistory, InMemoryChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory

from app.config import settings
from app.services.supabase_service import get_profile, get_user_reports, get_report_by_id

logger = logging.getLogger(__name__)


# ============================================================================
# SYSTEM PROMPT
# ============================================================================

SYSTEM_PROMPT = """You are FitMe AI Coach, a friendly personal fitness trainer.

YOUR STYLE:
- Explain everything simply, for a normal trainee with no science background.
- Avoid complicated medical or academic language.
- Always give practical, step-by-step advice the user can act on today.
- Be encouraging and positive, like a supportive coach.

USE THE USER'S DATA:
- You are given the user's profile and recent training history below.
- Use it proactively. Never ask the user for their age, weight, height,
  goal, level or history if it is already provided — you already know it.
- Reference their real numbers and their detected form mistakes when relevant.

STAY ON TOPIC (VERY IMPORTANT):
- You ONLY discuss fitness: workouts, exercises, exercise technique, training
  plans, recovery, muscle groups, form improvement, mistakes from their
  reports, fitness progress, and nutrition related to training.
- If the user asks about anything unrelated (politics, coding, general trivia,
  relationships, etc.), politely refuse in one short sentence and remind them
  you are only a fitness coach, then offer to help with a fitness topic.

SAFETY:
- Never give dangerous or extreme advice.
- If the user describes pain, an injury, or a medical condition, recommend they
  see a doctor or qualified professional. Do not diagnose medical conditions.
- Encourage gradual, sustainable progress.

Here is the current user's information:
{user_context}
"""


# ============================================================================
# PER-USER CONVERSATION MEMORY
# ============================================================================

# Maps user_id -> chat history. In-memory only (resets on server restart).
# This keeps each user's conversation isolated from every other user.
_user_histories: Dict[str, InMemoryChatMessageHistory] = {}


def _get_history(user_id: str) -> BaseChatMessageHistory:
    """Return (creating if needed) the chat history for a single user."""
    if user_id not in _user_histories:
        _user_histories[user_id] = InMemoryChatMessageHistory()
    return _user_histories[user_id]


def reset_user_memory(user_id: str) -> None:
    """Clear a single user's conversation history (start a fresh chat)."""
    _user_histories.pop(user_id, None)


# ============================================================================
# LLM + CHAIN (built lazily so the app still boots without an API key)
# ============================================================================

_chain_with_history: Optional[RunnableWithMessageHistory] = None


def _build_chain() -> RunnableWithMessageHistory:
    """Construct the LangChain runnable with message history, once."""
    global _chain_with_history
    if _chain_with_history is not None:
        return _chain_with_history

    if not settings.groq_api_key:
        raise RuntimeError(
            "AI Coach is not configured. Set GROQ_API_KEY in the backend "
            ".env file (free key at https://console.groq.com/keys)."
        )

    llm = ChatGroq(
        model=settings.coach_model,
        api_key=settings.groq_api_key,
        temperature=0.6,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{input}"),
    ])

    chain = prompt | llm

    _chain_with_history = RunnableWithMessageHistory(
        chain,
        lambda session_id: _get_history(session_id),
        input_messages_key="input",
        history_messages_key="history",
    )
    return _chain_with_history


# ============================================================================
# USER CONTEXT BUILDER (reads existing Supabase data)
# ============================================================================

_GOAL_LABELS = {
    "lose_weight": "lose weight / lose fat",
    "build_muscle": "build muscle",
    "maintain": "maintain fitness",
}


def build_user_context(user_id: str) -> str:
    """
    Assemble a human-readable summary of the user's profile and training
    history to inject into the system prompt. Fails soft: any missing piece
    is simply omitted rather than raising.
    """
    lines: List[str] = []

    # --- Profile ---
    try:
        profile = get_profile(user_id)
    except Exception as e:
        logger.warning(f"AI Coach: could not load profile for {user_id}: {e}")
        profile = None

    if profile:
        name = profile.get("full_name")
        if name:
            lines.append(f"- Name: {name}")
        if profile.get("gender"):
            lines.append(f"- Gender: {profile['gender']}")
        if profile.get("age"):
            lines.append(f"- Age: {profile['age']} years")
        if profile.get("height"):
            lines.append(f"- Height: {profile['height']} cm")
        if profile.get("weight"):
            lines.append(f"- Weight: {profile['weight']} kg")
        goal = profile.get("fitness_goal")
        if goal:
            lines.append(f"- Goal: {_GOAL_LABELS.get(goal, goal)}")
        if profile.get("training_days_per_week"):
            lines.append(f"- Trains {profile['training_days_per_week']} days per week")
        if profile.get("preferred_workout_duration"):
            lines.append(f"- Preferred session length: {profile['preferred_workout_duration']} minutes")
    else:
        lines.append("- No profile details available yet.")

    # --- Recent sessions & reports ---
    try:
        reports = get_user_reports(user_id) or []
    except Exception as e:
        logger.warning(f"AI Coach: could not load reports for {user_id}: {e}")
        reports = []

    if reports:
        lines.append(f"- Total recorded sessions: {len(reports)}")
        recent = reports[:3]
        lines.append("- Recent sessions:")
        for r in recent:
            ex = r.get("exercise_type", "workout")
            score = r.get("form_score")
            mistakes = r.get("total_mistakes", 0)
            score_txt = f"form score {score}/100, " if score is not None else ""
            lines.append(f"    • {ex}: {score_txt}{mistakes} mistake(s)")

        # Pull detailed mistakes from the most recent report
        try:
            top = get_report_by_id(reports[0]["id"], user_id)
            full = (top or {}).get("full_report") or {}
            detailed = full.get("mistakes") or []
            if detailed:
                lines.append("- Most recent detected form mistakes:")
                for m in detailed[:5]:
                    msg = m.get("mistake_message") or m.get("mistake_type", "form issue")
                    count = m.get("count")
                    count_txt = f" (x{count})" if count else ""
                    lines.append(f"    • {msg}{count_txt}")
        except Exception as e:
            logger.warning(f"AI Coach: could not load detailed report for {user_id}: {e}")
    else:
        lines.append("- No training sessions recorded yet.")

    return "\n".join(lines)


# ============================================================================
# PUBLIC API
# ============================================================================

def is_configured() -> bool:
    """True if an LLM API key is available."""
    return bool(settings.groq_api_key)


def chat(user_id: str, message: str) -> str:
    """
    Send a user message to the AI Coach and return its reply.

    The user's profile/history context is rebuilt on each call (so advice
    always reflects their latest data), and conversation memory is keyed by
    user_id so prior turns are remembered.
    """
    chain = _build_chain()
    user_context = build_user_context(user_id)

    response = chain.invoke(
        {"input": message, "user_context": user_context},
        config={"configurable": {"session_id": user_id}},
    )

    # ChatGroq returns an AIMessage; .content holds the text.
    return getattr(response, "content", str(response))
