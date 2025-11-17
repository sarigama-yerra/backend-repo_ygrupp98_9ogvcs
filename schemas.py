"""
Database Schemas for Study Space Station

Each Pydantic model maps to a MongoDB collection (name = lowercase of class name).
"""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from datetime import datetime

# Users who participate in sessions and leaderboards
class Astronaut(BaseModel):
    username: str = Field(..., description="Public handle")
    avatar: Optional[str] = Field(None, description="Unlocked avatar id or URL")
    level: int = Field(1, ge=1, description="Player level")
    xp: int = Field(0, ge=0, description="Experience points")
    streak: int = Field(0, ge=0, description="Daily streak in days")

# Study session logs (Pomodoro cycles)
class Session(BaseModel):
    user: str = Field(..., description="username of astronaut")
    duration_min: int = Field(..., ge=1, description="Focused minutes in this session")
    break_min: int = Field(..., ge=0, description="Break minutes configured")
    status: Literal["completed", "cancelled"] = Field(...)
    points_earned: int = Field(0, ge=0)
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

# Tips stored in Knowledge Vault
class Tip(BaseModel):
    title: str
    category: Literal["Memory", "Focus", "Exam Prep", "Crazy Methods"]
    tiktok_url: Optional[str] = None
    tags: List[str] = []

# Music playlists for Orbit Radio
class Playlist(BaseModel):
    name: Literal["Lofi", "Classical", "Ambient", "Nature"]
    description: Optional[str] = None
    cover: Optional[str] = None
    tracks: List[dict] = Field(default_factory=list, description="List of tracks with {title, url}")

# Achievement badges
class Achievement(BaseModel):
    key: str = Field(..., description="Unique badge key")
    name: str
    description: str
    icon: Optional[str] = None

