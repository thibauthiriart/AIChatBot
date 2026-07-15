from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: HttpUrl


class Site(BaseModel):
    id: str
    name: str
    base_url: str


class IngestRequest(BaseModel):
    site_id: Optional[str] = None
    urls: list[HttpUrl] = Field(min_length=1, max_length=200)


class IngestResult(BaseModel):
    indexed_documents: int
    indexed_chunks: int


class ConversationMessage(BaseModel):
    role: str = Field(pattern="^(visitor|agent)$")
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    site_id: Optional[str] = None
    client_id: Optional[str] = None
    message: str = Field(min_length=1, max_length=1200)
    history: list[ConversationMessage] = Field(default_factory=list, max_length=12)


class RouteDecision(BaseModel):
    decision: str = Field(pattern="^(allow|deny)$")
    category: str = Field(pattern="^(greeting|knowledge|appointment|deny)$")
    reason: str = Field(min_length=1, max_length=200)


class RewriteDecision(BaseModel):
    rewritten_message: str = Field(min_length=1, max_length=1200)
    used_history: bool


class ModelUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatUsage(BaseModel):
    route: Optional[ModelUsage] = None
    rewrite: Optional[ModelUsage] = None
    answer: Optional[ModelUsage] = None
    total: Optional[ModelUsage] = None


class Source(BaseModel):
    url: str
    title: str
    score: float


class ClientCreate(BaseModel):
    site_id: Optional[str] = None
    name: str = Field(min_length=1, max_length=160)
    short_name: Optional[str] = Field(default=None, max_length=80)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    sector: str = Field(default="", max_length=120)
    status: str = Field(default="", max_length=80)
    summary: str = Field(default="", max_length=4000)
    external_ref: str = Field(default="", max_length=120)


class ClientSummary(BaseModel):
    id: str
    site_id: str
    name: str
    short_name: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)
    sector: str = ""
    status: str = ""
    summary: str = ""
    external_ref: str = ""


class ClientProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    status: str = Field(default="", max_length=80)
    summary: str = Field(default="", max_length=4000)
    started_on: Optional[str] = Field(default=None, max_length=32)
    due_on: Optional[str] = Field(default=None, max_length=32)


class ClientProjectSummary(BaseModel):
    id: str
    client_id: str
    name: str
    status: str = ""
    summary: str = ""
    started_on: Optional[str] = None
    due_on: Optional[str] = None


class ClientArtifactCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    kind: str = Field(default="report", max_length=80)
    content: str = Field(min_length=1, max_length=20000)
    project_id: Optional[str] = None


class ClientArtifactSummary(BaseModel):
    id: str
    client_id: str
    project_id: Optional[str] = None
    title: str
    kind: str


class ClientEventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    event_type: str = Field(default="note", max_length=80)
    details: str = Field(default="", max_length=8000)
    event_at: Optional[str] = Field(default=None, max_length=64)
    project_id: Optional[str] = None


class ClientEventSummary(BaseModel):
    id: str
    client_id: str
    project_id: Optional[str] = None
    title: str
    event_type: str
    details: str = ""
    event_at: str


class ClientContextSummary(BaseModel):
    client: ClientSummary
    projects: list[ClientProjectSummary] = Field(default_factory=list)
    artifacts: list[ClientArtifactSummary] = Field(default_factory=list)
    recent_events: list[ClientEventSummary] = Field(default_factory=list)


class NootaParticipant(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    email: str = Field(default="", max_length=320)
    role: str = Field(default="", max_length=120)
    company: str = Field(default="", max_length=160)


class NootaActionItem(BaseModel):
    description: str = Field(min_length=1, max_length=1000)
    owner: str = Field(default="", max_length=160)
    due_date: str = Field(default="", max_length=64)


class NootaReportImport(BaseModel):
    site_id: Optional[str] = None
    client_id: Optional[str] = None
    client_name: str = Field(min_length=1, max_length=160)
    client_aliases: list[str] = Field(default_factory=list, max_length=20)
    project_name: str = Field(default="", max_length=160)
    meeting_title: str = Field(min_length=1, max_length=200)
    meeting_at: Optional[str] = Field(default=None, max_length=64)
    external_id: str = Field(default="", max_length=160)
    source_url: str = Field(default="", max_length=2000)
    language: str = Field(default="fr", max_length=32)
    summary: str = Field(default="", max_length=6000)
    key_points: list[str] = Field(default_factory=list, max_length=40)
    decisions: list[str] = Field(default_factory=list, max_length=40)
    action_items: list[NootaActionItem] = Field(default_factory=list, max_length=100)
    transcript: str = Field(default="", max_length=50000)
    participants: list[NootaParticipant] = Field(default_factory=list, max_length=100)


class NootaImportResponse(BaseModel):
    client: ClientSummary
    project: Optional[ClientProjectSummary] = None
    artifact: ClientArtifactSummary
    event: ClientEventSummary
    formatted_report: str


class NootaDriveSyncRequest(BaseModel):
    site_id: Optional[str] = None
    folder_id: Optional[str] = Field(default=None, max_length=200)
    limit: int = Field(default=20, ge=1, le=200)


class NootaDriveImportedItem(BaseModel):
    external_id: str
    file_name: str
    client_name: str
    project_name: str = ""
    artifact_id: str


class CalendarEventSuggestion(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start: str = Field(min_length=1, max_length=64)
    end: str = Field(min_length=1, max_length=64)
    timezone: str = Field(min_length=1, max_length=64)
    source_excerpt: str = Field(default="", max_length=500)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class NootaDriveSyncResponse(BaseModel):
    scanned_files: int
    imported_files: int
    skipped_files: int
    items: list[NootaDriveImportedItem] = Field(default_factory=list)


class NootaDrivePendingItem(BaseModel):
    external_id: str
    file_name: str
    client_name: str
    project_name: str = ""
    meeting_title: str
    meeting_at: Optional[str] = None
    formatted_report: str = ""
    suggested_appointments: list[CalendarEventSuggestion] = Field(default_factory=list)


class NootaDrivePendingListResponse(BaseModel):
    items: list[NootaDrivePendingItem] = Field(default_factory=list)


class NootaDriveImportOneRequest(BaseModel):
    site_id: Optional[str] = None
    external_id: str = Field(min_length=1, max_length=200)
    folder_id: Optional[str] = Field(default=None, max_length=200)


class NootaDriveImportAndEmailRequest(BaseModel):
    site_id: Optional[str] = None
    external_id: str = Field(min_length=1, max_length=200)
    recipient_email: str = Field(min_length=3, max_length=320)
    folder_id: Optional[str] = Field(default=None, max_length=200)


class NootaDriveImportAndEmailResponse(BaseModel):
    imported_item: NootaDriveImportedItem
    recipient_email: str
    mail_sent: bool = True
    scheduled_appointments: list["NootaDriveScheduleSuggestionResponse"] = Field(default_factory=list)


class NootaDriveFileInfo(BaseModel):
    external_id: str
    file_name: str
    modified_time: str = ""


class NootaDriveStatusResponse(BaseModel):
    checked_at: str
    scanned_files: int
    pending_files: int
    imported_reports: int = 0
    latest_files: list[NootaDriveFileInfo] = Field(default_factory=list)


class BookingSlot(BaseModel):
    start: str = Field(min_length=1, max_length=64)
    end: str = Field(min_length=1, max_length=64)
    timezone: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=120)


class BookingRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    start: str = Field(min_length=1, max_length=64)
    end: str = Field(min_length=1, max_length=64)
    timezone: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class CalendarEventRequest(BaseModel):
    summary: str = Field(min_length=1, max_length=200)
    start: str = Field(min_length=1, max_length=64)
    end: str = Field(min_length=1, max_length=64)
    timezone: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=4000)
    attendee_name: str = Field(default="", max_length=120)
    attendee_email: str = Field(default="", max_length=320)


class BookingConfirmation(BaseModel):
    event_id: str = Field(min_length=1, max_length=256)
    html_link: Optional[str] = Field(default=None, max_length=2000)


class BookingResult(BaseModel):
    status: str = Field(pattern="^(needs_info|slot_selection|confirmation|confirmed|error)$")
    message: str = Field(min_length=1, max_length=4000)
    slots: list[BookingSlot] = Field(default_factory=list)
    confirmation: Optional[BookingConfirmation] = None
    request: Optional[BookingRequest] = None


class AppointmentNotification(BaseModel):
    id: str
    site_id: str
    client_name: str = ""
    client_email: str = ""
    scheduled_for: str
    timezone: str
    created_at: str
    html_link: Optional[str] = None


class AppointmentNotificationListResponse(BaseModel):
    items: list[AppointmentNotification] = Field(default_factory=list)


class NootaDriveScheduleSuggestionRequest(BaseModel):
    site_id: Optional[str] = None
    external_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    start: str = Field(min_length=1, max_length=64)
    end: str = Field(min_length=1, max_length=64)
    timezone: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=4000)
    folder_id: Optional[str] = Field(default=None, max_length=200)


class NootaDriveScheduleSuggestionResponse(BaseModel):
    notification_id: Optional[str] = None
    event_id: str = Field(min_length=1, max_length=256)
    html_link: Optional[str] = Field(default=None, max_length=2000)
    title: str = Field(min_length=1, max_length=200)
    start: str = Field(min_length=1, max_length=64)
    end: str = Field(min_length=1, max_length=64)
    timezone: str = Field(min_length=1, max_length=64)


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source] = Field(default_factory=list)
    client: Optional[ClientSummary] = None
    usage: Optional[ChatUsage] = None


class WidgetConfigResponse(BaseModel):
    widget_enabled: bool
