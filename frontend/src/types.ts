import type { ChatMessage } from './chatPayload'

export type SourceItem = {
  url: string
  title: string
  score: number
}

export type ClientItem = {
  id: string
  name: string
  short_name?: string | null
  status?: string
  sector?: string
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

export type NootaPendingNotification = {
  external_id: string
  file_name: string
  client_name: string
  project_name: string
  meeting_title: string
  meeting_at?: string | null
  formatted_report: string
  suggested_appointments: SuggestedAppointment[]
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

export type DriveStatusFile = {
  external_id: string
  file_name: string
  modified_time: string
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
