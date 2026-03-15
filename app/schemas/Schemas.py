"""
app/schemas/Schemas.py
All Pydantic models for request validation and response serialization.
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ─── Enums ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    ADMIN            = "admin"
    LEADER           = "leader"
    CITIZEN          = "citizen"
    HIGHER_AUTHORITY = "higher_authority"


class IssueStatus(str, Enum):
    OPEN        = "OPEN"
    RESOLVED_L1 = "RESOLVED_L1"
    RESOLVED_L2 = "RESOLVED_L2"
    ESCALATED   = "ESCALATED"
    CLOSED      = "CLOSED"


class TaskStatus(str, Enum):
    PENDING     = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    CANCELLED   = "cancelled"


class UrgencyLevel(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


# ─── Location ─────────────────────────────────────────────────────────────────

class LocationSchema(BaseModel):
    """
    Used for both issue location and leader_location.
    latitude / longitude  — map display / geo queries.
    state / city / town   — leader assignment matching (any one match is enough).
    """
    latitude:  Optional[float] = None
    longitude: Optional[float] = None
    address:   Optional[str]   = None
    state:     Optional[str]   = None
    city:      Optional[str]   = None
    town:      Optional[str]   = None

    class Config:
        extra = "ignore"   # silently drop unknown fields from old clients


# ─── Auth Schemas ─────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name:     str      = Field(..., min_length=2, max_length=100)
    email:    EmailStr
    password: str      = Field(..., min_length=6)
    role:     UserRole = UserRole.CITIZEN

    # Only relevant when role == "leader"
    leader_location: Optional[LocationSchema] = None
    department:      Optional[str]            = None
    phone: Optional[str] = None

    def validate_leader_fields(self) -> None:
        """Call in the route to enforce that leaders provide a location."""
        if self.role == UserRole.LEADER and not self.leader_location:
            raise ValueError("leader_location is required for leader registration")


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    role:         str
    user_id:      str
    name:         str


class UserResponse(BaseModel):
    id:              str
    name:            str
    email:           str
    role:            str
    failed_cases:    int
    created_at:      datetime
    department:      Optional[str]            = None
    leader_location: Optional[LocationSchema] = None


# ─── Issue Schemas ────────────────────────────────────────────────────────────

class IssueCreate(BaseModel):
    description: str           = Field(...)
    category:    Optional[str] = None
    location:    Optional[LocationSchema] = None


class ResolutionNote(BaseModel):
    attempt:     int
    notes:       str
    resolved_by: str
    resolved_at: str


class IssueResponse(BaseModel):
    id:                  str
    title:               str
    description:         str
    category:            Optional[str]       = None
    priority_score:      Optional[float]     = None
    urgency_level:       Optional[str]       = None   # derived from priority_score if needed
    location:            Optional[dict]      = None
    user_id:             str
    leader_id:           Optional[str]       = None
    resolution_attempts: int                 = 0
    status:              str
    image_url:           Optional[str]       = None   # single Cloudinary URL
    audio_url:           Optional[str]       = None
    resolution_notes:    List[ResolutionNote] = []
    created_at:          datetime
    citizen_name:        Optional[str]       = None
    leader_name:         Optional[str]       = None


class IssueResolveRequest(BaseModel):
    resolution_notes: str = Field(..., min_length=5)


class CitizenVerificationRequest(BaseModel):
    approved: bool
    feedback: Optional[str] = None


# ─── Task Schemas ─────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    issue_id:    str
    assigned_to: str
    deadline:    datetime
    description: Optional[str] = None


class TaskUpdate(BaseModel):
    status:      Optional[TaskStatus] = None
    assigned_to: Optional[str]        = None
    deadline:    Optional[datetime]   = None
    description: Optional[str]        = None


class TaskResponse(BaseModel):
    id:            str
    issue_id:      str
    assigned_to:   str
    deadline:      datetime
    status:        str
    description:   Optional[str] = None
    created_at:    datetime
    issue_title:   Optional[str] = None
    assignee_name: Optional[str] = None


# ─── Verification Schemas ─────────────────────────────────────────────────────

class VerificationResponse(BaseModel):
    id:               str
    issue_id:          str
    before_image_url: Optional[str]   = None
    after_image_url:  Optional[str]   = None
    latitude:         Optional[float] = None
    longitude:        Optional[float] = None
    timestamp:        datetime


# ─── Sentiment Schemas ────────────────────────────────────────────────────────

class SentimentResponse(BaseModel):
    id:         str
    issue_id:   str
    positive:   float
    negative:   float
    neutral:    float
    created_at: datetime


# ─── Dashboard Schemas ────────────────────────────────────────────────────────

class LeaderMetrics(BaseModel):
    total_issues:    int
    completed_tasks: int
    pending_tasks:   int
    escalated_cases: int
    failed_cases:    int
    active_problems: int


class LeaderRanking(BaseModel):
    leader_id:       str
    name:            str
    email:           str
    failed_cases:    int
    total_issues:    int
    resolved_issues: int


class AdminDashboard(BaseModel):
    total_citizens:   int
    total_leaders:    int
    total_issues:     int
    open_issues:      int
    resolved_issues:  int
    escalated_issues: int
    leader_rankings:  List[LeaderRanking]


class CitizenDashboardResponse(BaseModel):
    total_submitted:  int
    open_issues:      int
    closed_issues:    int
    escalated_issues: int