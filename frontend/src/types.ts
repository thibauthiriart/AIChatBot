import type { ChatMessage } from './chatPayload'

export type SourceItem = {
  url: string
  title: string
  score: number
}

export type ClientItem = {
  id: string
  site_id?: string
  name: string
  short_name?: string | null
  aliases?: string[]
  status?: string
  sector?: string
  summary?: string
  external_ref?: string
}

export type ClientCreatePayload = {
  site_id?: string
  name: string
  short_name?: string | null
  aliases?: string[]
  sector?: string
  status?: string
  summary?: string
  external_ref?: string
}

export type ClientUpdatePayload = Omit<ClientCreatePayload, 'site_id'>

export type ClientProjectTaskStatus = 'proposed' | 'done' | 'later' | 'abandoned'

export type ClientProject = {
  id: string
  client_id: string
  name: string
  status: string
  summary: string
  started_on?: string | null
  due_on?: string | null
}

export type ClientArtifact = {
  id: string
  client_id: string
  project_id?: string | null
  title: string
  kind: string
  excerpt?: string
  updated_at?: string
}

export type ClientEvent = {
  id: string
  client_id: string
  project_id?: string | null
  title: string
  event_type: string
  details: string
  event_at: string
}

export type ClientProjectTask = {
  id: string
  client_id: string
  project_id?: string | null
  project_name: string
  artifact_id?: string | null
  artifact_title: string
  title: string
  owner: string
  due_date: string
  status: ClientProjectTaskStatus
  source_excerpt: string
  created_at: string
  updated_at: string
}

export type ChatResponse = {
  answer: string
  sources?: SourceItem[]
  client?: ClientItem | null
}

export type AppointmentNotification = {
  id: string
  site_id: string
  client_name: string
  client_email: string
  scheduled_for: string
  timezone: string
  created_at: string
  html_link?: string | null
}

export type SuggestedAppointment = {
  title: string
  start: string
  end: string
  timezone: string
  source_excerpt: string
  confidence: number
}

export type SuggestedTask = {
  key?: string
  title: string
  owner?: string
  due_date?: string
  source_excerpt?: string
}

export type NootaPendingNotification = {
  external_id: string
  file_name: string
  client_name: string
  detected_client_name?: string
  project_name: string
  meeting_title: string
  meeting_at?: string | null
  formatted_report: string
  suggested_appointments: SuggestedAppointment[]
  suggested_tasks?: SuggestedTask[]
}

export type ScheduledSuggestionResponse = {
  notification_id?: string | null
  event_id: string
  html_link?: string | null
  title: string
  start: string
  end: string
  timezone: string
}

export type ImportAndEmailResponse = {
  imported_item: {
    external_id: string
    file_name: string
    client_name: string
    project_name: string
    artifact_id: string
  }
  recipient_email: string
  mail_sent: boolean
  scheduled_appointments?: ScheduledSuggestionResponse[]
}

export type RewriteReportResponse = {
  external_id: string
  formatted_report: string
}

export type DriveStatusFile = {
  external_id: string
  file_name: string
  modified_time: string
  imported?: boolean
  pending?: boolean
}

export type DriveStatus = {
  checked_at: string
  scanned_files: number
  pending_files: number
  imported_reports: number
  latest_files: DriveStatusFile[]
}

export type MessageWithMeta = ChatMessage & {
  createdAt: string
  sources?: SourceItem[]
  client?: ClientItem | null
}

export type ConversationRecord = {
  id: string
  title: string
  titleEdited?: boolean
  updatedAt: string
  messages: MessageWithMeta[]
}

export type OfferProjectRecord = {
  id: string
  title: string
  titleEdited?: boolean
  updatedAt: string
  messages: MessageWithMeta[]
}

export type OfferMissingItem = {
  key: string
  label: string
  prompt: string
  status: 'missing' | 'completed'
  priority: 'critical' | 'important' | 'optional'
  answer: string
}

export type OfferProjectSummary = {
  id: string
  title: string
  client_name: string
  sector: string
  status: string
  updated_at: string
  completion_ratio: number
}

export type OfferProjectMessage = {
  id: string
  role: 'visitor' | 'agent'
  content: string
  created_at: string
}

export type OfferProjectEmailSummary = {
  id: string
  subject: string
  sender: string
  excerpt: string
  created_at: string
}

export type OfferProjectFileSummary = {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  excerpt: string
  created_at: string
}

export type OfferReferenceSummary = {
  id: string
  title: string
  client_name: string
  sector: string
  offer_type: string
  delivery_timeline: string
  pricing_notes: string
  team_notes: string
  tags: string[]
  excerpt: string
  created_at: string
}

export type TeamProfileSummary = {
  id: string
  full_name: string
  role: string
  seniority: string
  skills: string[]
  sectors: string[]
  bio: string
  availability_notes: string
}

export type OfferProjectExportSummary = {
  id: string
  format: string
  filename: string
  created_at: string
}

export type OfferTaskChoiceDecision = 'pending' | 'include' | 'later' | 'forgotten'

export type OfferTaskChoice = {
  task_key: string
  title: string
  detail: string
  source: string
  source_id: string
  decision: OfferTaskChoiceDecision
  created_at: string
  updated_at: string
}

export type OfferProjectContext = {
  project: OfferProjectSummary
  request_summary: string
  scope_details: string
  deliverables: string
  planning_details: string
  pricing_details: string
  time_spent_details: string
  team_details: string
  constraints: string
  missing_items: OfferMissingItem[]
  messages: OfferProjectMessage[]
  emails: OfferProjectEmailSummary[]
  files: OfferProjectFileSummary[]
  references: OfferReferenceSummary[]
  suggested_team_profiles: TeamProfileSummary[]
  exports: OfferProjectExportSummary[]
  generated_offer_markdown: string
  linked_client?: ClientItem | null
  linked_client_project?: ClientProject | null
  client_artifacts?: ClientArtifact[]
  client_recent_events?: ClientEvent[]
  client_project_tasks?: ClientProjectTask[]
  task_choices?: OfferTaskChoice[]
}

export type OfferAssistantResponse = {
  message: OfferProjectMessage
  project: OfferProjectSummary
  missing_items: OfferMissingItem[]
  generated_offer_markdown: string
  exports: OfferProjectExportSummary[]
}
