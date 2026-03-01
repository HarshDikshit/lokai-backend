from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# Enums
class UserRole(str, Enum):
    ADMIN = "admin"
    LEADER = "leader"
    CITIZEN = "citizen"
    HIGHER_AUTHORITY = "higher_authority"


class IssueStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_L1 = "RESOLVED_L1"
    RESOLVED_L2 = "RESOLVED_L2"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class UrgencyLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ─── Auth Schemas ───────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=6)
    role: UserRole = UserRole.CITIZEN


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    name: str


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str
    failed_cases: int
    created_at: datetime


# ─── Issue Schemas ───────────────────────────────────────────────────────────
class LocationSchema(BaseModel):
    latitude: float
    longitude: float
    address: Optional[str] = None


class IssueCreate(BaseModel):
    title: str = Field(..., min_length=5, max_length=200)
    description: str = Field(..., min_length=10)
    category: Optional[str] = None
    location: LocationSchema


class IssueResponse(BaseModel):
    id: str
    title: str
    description: str
    category: Optional[str]
    priority_score: Optional[float]
    urgency_level: Optional[str]
    location: Optional[dict]
    user_id: str
    leader_id: Optional[str]
    resolution_attempts: int
    status: str
    image_urls: List[str]
    audio_url: Optional[str]
    created_at: datetime
    citizen_name: Optional[str] = None
    leader_name: Optional[str] = None


class IssueResolveRequest(BaseModel):
    resolution_notes: str = Field(..., min_length=5)


class CitizenVerificationRequest(BaseModel):
    approved: bool
    feedback: Optional[str] = None


# ─── Task Schemas ────────────────────────────────────────────────────────────
class TaskCreate(BaseModel):
    issue_id: str
    assigned_to: str
    deadline: datetime
    description: Optional[str] = None


class TaskUpdate(BaseModel):
    status: Optional[TaskStatus] = None
    assigned_to: Optional[str] = None
    deadline: Optional[datetime] = None
    description: Optional[str] = None


class TaskResponse(BaseModel):
    id: str
    issue_id: str
    assigned_to: str
    deadline: datetime
    status: str
    description: Optional[str]
    created_at: datetime
    issue_title: Optional[str] = None
    assignee_name: Optional[str] = None


# ─── Verification Schemas ────────────────────────────────────────────────────
class VerificationResponse(BaseModel):
    id: str
    task_id: str
    before_image_url: Optional[str]
    after_image_url: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    timestamp: datetime


# ─── Sentiment Schemas ────────────────────────────────────────────────────────
class SentimentResponse(BaseModel):
    id: str
    issue_id: str
    positive: float
    negative: float
    neutral: float
    created_at: datetime


# ─── Dashboard Schemas ───────────────────────────────────────────────────────
class LeaderMetrics(BaseModel):
    total_issues: int
    completed_tasks: int
    pending_tasks: int
    escalated_cases: int
    failed_cases: int
    active_problems: int


class LeaderRanking(BaseModel):
    leader_id: str
    name: str
    email: str
    failed_cases: int
    total_issues: int
    resolved_issues: int


class AdminDashboard(BaseModel):
    total_citizens: int
    total_leaders: int
    total_issues: int
    open_issues: int
    resolved_issues: int
    escalated_issues: int
    leader_rankings: List[LeaderRanking]