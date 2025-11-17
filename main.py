import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database import db, create_document, get_documents

app = FastAPI(title="Study Space Station API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------
# Pydantic request models
# ----------------------
class CompleteSessionRequest(BaseModel):
    user: str
    duration_min: int = Field(ge=1)
    break_min: int = Field(ge=0, default=5)
    status: Literal["completed", "cancelled"] = "completed"


class PlanRequest(BaseModel):
    subject: str
    timeframe_days: int = Field(ge=1, le=60)
    daily_hours: float = Field(ge=0.5, le=12)
    learning_style: Literal["visual", "auditory", "reading", "kinesthetic", "mixed"] = "mixed"


# ----------------------
# Helpers
# ----------------------
POINTS_PER_MIN = 2  # base points per focus minute
BONUS_COMPLETED = 25  # completion bonus for finished capsule


def ensure_astronaut(username: str):
    existing = list(db["astronaut"].find({"username": username}).limit(1)) if db else []
    if existing:
        return existing[0]
    doc = {
        "username": username,
        "avatar": None,
        "level": 1,
        "xp": 0,
        "streak": 0,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    inserted = db["astronaut"].insert_one(doc)
    doc["_id"] = inserted.inserted_id
    return doc


def add_xp_and_level(username: str, delta_xp: int):
    user = ensure_astronaut(username)
    new_xp = int(user.get("xp", 0)) + int(delta_xp)
    # simple leveling curve: level up every 250 xp
    level = max(1, (new_xp // 250) + 1)
    db["astronaut"].update_one(
        {"username": username},
        {"$set": {"xp": new_xp, "level": level, "updated_at": datetime.now(timezone.utc)}},
    )
    return {"xp": new_xp, "level": level}


def update_streak(username: str):
    # streak increments if last session not older than yesterday
    today = datetime.now(timezone.utc).date()
    last = db["session"].find({"user": username, "status": "completed"}).sort("ended_at", -1).limit(1)
    last_dt = None
    for l in last:
        last_dt = l.get("ended_at")
    user = ensure_astronaut(username)
    current_streak = int(user.get("streak", 0))
    if last_dt:
        last_date = last_dt.date() if isinstance(last_dt, datetime) else today
        if last_date == today:
            # already counted today
            return current_streak
        if last_date == today - timedelta(days=1):
            current_streak += 1
        else:
            current_streak = 1
    else:
        current_streak = 1
    db["astronaut"].update_one({"username": username}, {"$set": {"streak": current_streak}})
    return current_streak


# ----------------------
# Basic endpoints
# ----------------------
@app.get("/")
def root():
    return {"service": "Study Space Station API", "status": "ok"}


@app.get("/test")
def test_database():
    info = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "collections": [],
    }
    try:
        if db is not None:
            info["database"] = "✅ Connected"
            info["collections"] = db.list_collection_names()
    except Exception as e:
        info["database"] = f"⚠️ {str(e)[:80]}"
    return info


# ----------------------
# Knowledge Vault (Tips)
# ----------------------
@app.get("/api/tips")
def list_tips(category: Optional[str] = None, q: Optional[str] = None, limit: int = 24):
    if db is None:
        raise HTTPException(status_code=500, detail="Database unavailable")
    filt = {}
    if category:
        filt["category"] = category
    if q:
        filt["$or"] = [{"title": {"$regex": q, "$options": "i"}}, {"tags": {"$in": [q]}}]
    docs = list(db["tip"].find(filt).limit(limit))
    for d in docs:
        d["_id"] = str(d["_id"])  # jsonify
    return {"items": docs}


@app.get("/api/tips/random")
def random_tip(category: Optional[str] = None):
    if db is None:
        raise HTTPException(status_code=500, detail="Database unavailable")
    pipeline = []
    if category:
        pipeline.append({"$match": {"category": category}})
    pipeline.append({"$sample": {"size": 1}})
    sampled = list(db["tip"].aggregate(pipeline))
    if not sampled:
        raise HTTPException(status_code=404, detail="No tips found")
    tip = sampled[0]
    tip["_id"] = str(tip["_id"])
    return tip


# ----------------------
# Orbit Radio (Playlists)
# ----------------------
@app.get("/api/playlists")
def playlists():
    if db is None:
        raise HTTPException(status_code=500, detail="Database unavailable")
    docs = list(db["playlist"].find({}))
    for d in docs:
        d["_id"] = str(d["_id"])  # jsonify
    # Provide safe defaults if collection empty
    if not docs:
        docs = [
            {
                "name": "Lofi",
                "description": "Chill beats for deep focus.",
                "cover": None,
                "tracks": [],
            },
            {
                "name": "Ambient",
                "description": "Soft textures and cosmic drones.",
                "cover": None,
                "tracks": [],
            },
            {
                "name": "Nature",
                "description": "Rain, wind, and distant thunder.",
                "cover": None,
                "tracks": [],
            },
        ]
    return {"items": docs}


# ----------------------
# Focus Capsule (Sessions + Points)
# ----------------------
@app.post("/api/sessions/complete")
def complete_session(payload: CompleteSessionRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database unavailable")
    now = datetime.now(timezone.utc)
    points = payload.duration_min * POINTS_PER_MIN
    if payload.status == "completed":
        points += BONUS_COMPLETED
    # Write session
    session_doc = {
        "user": payload.user,
        "duration_min": payload.duration_min,
        "break_min": payload.break_min,
        "status": payload.status,
        "points_earned": points,
        "started_at": now - timedelta(minutes=payload.duration_min + payload.break_min),
        "ended_at": now,
        "created_at": now,
        "updated_at": now,
    }
    sid = db["session"].insert_one(session_doc).inserted_id

    # Update XP / Level
    stats = add_xp_and_level(payload.user, points)
    # Update streak when completed
    streak = update_streak(payload.user) if payload.status == "completed" else ensure_astronaut(payload.user).get("streak", 0)

    return {
        "session_id": str(sid),
        "points": points,
        "xp": stats["xp"],
        "level": stats["level"],
        "streak": streak,
    }


@app.get("/api/leaderboard")
def leaderboard(period: Literal["week", "all"] = "week", limit: int = 10):
    if db is None:
        raise HTTPException(status_code=500, detail="Database unavailable")
    filt = {"status": "completed"}
    if period == "week":
        since = datetime.now(timezone.utc) - timedelta(days=7)
        filt["ended_at"] = {"$gte": since}
    pipeline = [
        {"$match": filt},
        {"$group": {"_id": "$user", "points": {"$sum": "$points_earned"}}},
        {"$sort": {"points": -1}},
        {"$limit": limit},
    ]
    rows = list(db["session"].aggregate(pipeline))
    items = []
    for r in rows:
        user = db["astronaut"].find_one({"username": r["_id"]}) or {"level": 1}
        items.append({
            "username": r["_id"],
            "points": int(r["points"]),
            "level": int(user.get("level", 1)),
        })
    return {"items": items}


@app.get("/api/astronaut/{username}")
def get_astronaut(username: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database unavailable")
    user = db["astronaut"].find_one({"username": username})
    if not user:
        user = ensure_astronaut(username)
    user["_id"] = str(user.get("_id")) if user.get("_id") else None
    return user


# ----------------------
# Mission Planner (Study Plan Generator)
# ----------------------
@app.post("/api/plan")
def generate_plan(req: PlanRequest):
    # simple heuristic plan generator
    days = req.timeframe_days
    per_day_hours = req.daily_hours
    blocks = max(1, int(per_day_hours // 0.5))  # 30m blocks
    style_map = {
        "visual": ["Mind maps", "Diagram study", "Color-coded notes"],
        "auditory": ["Explain aloud", "Podcast recap", "Record and replay"],
        "reading": ["SQ3R method", "Active recall", "Cornell notes"],
        "kinesthetic": ["Practice questions", "Teach a friend", "Flashcards walk"],
        "mixed": ["Pomodoro x5", "Blurting", "Spaced repetition"],
    }
    methods = style_map.get(req.learning_style, style_map["mixed"])

    start = datetime.now(timezone.utc).date()
    schedule = []
    for i in range(days):
        date = start + timedelta(days=i)
        day_plan = {
            "date": date.isoformat(),
            "goal": f"{req.subject}: {int(per_day_hours*60)} min focus",
            "blocks": [
                {"label": f"Focus Block {b+1}", "minutes": 30, "method": methods[b % len(methods)]}
                for b in range(blocks)
            ],
        }
        schedule.append(day_plan)

    return {
        "subject": req.subject,
        "learning_style": req.learning_style,
        "daily_hours": per_day_hours,
        "timeframe_days": days,
        "schedule": schedule,
    }


# ----------------------
# Achievements (static list for now)
# ----------------------
ACHIEVEMENTS = [
    {"key": "first_launch", "name": "First Launch", "description": "Complete your first Focus Capsule."},
    {"key": "orbit_5", "name": "Low Orbit", "description": "Earn 500 Stellar Credits."},
    {"key": "streak_7", "name": "One Week Orbit", "description": "Maintain a 7-day streak."},
]


@app.get("/api/achievements")
def list_achievements():
    return {"items": ACHIEVEMENTS}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
