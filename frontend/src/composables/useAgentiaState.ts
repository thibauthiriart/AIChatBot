import { computed, ref } from 'vue'
import { buildRequestHistory, prepareOutgoingMessage, WELCOME_MESSAGE } from '../chatPayload'
import { getAppConfig } from '../config'
import type {
  AppointmentNotification,
  ChatResponse,
  ClientItem,
  ConversationRecord,
  DriveStatus,
  ImportAndEmailResponse,
  MessageWithMeta,
  NootaPendingNotification,
  ScheduledSuggestionResponse,
  SourceItem,
  SuggestedAppointment
} from '../types'

const config = getAppConfig()
const apiBaseUrl = config.apiUrl.replace(/\/$/, '')

function createMessage(role: MessageWithMeta['role'], content: string, extra: Partial<MessageWithMeta> = {}): MessageWithMeta {
  return {
    role,
    content,
    createdAt: new Date().toLocaleTimeString('fr-FR', {
      hour: '2-digit',
      minute: '2-digit'
    }),
    ...extra
  }
}

function createWelcomeMessages(): MessageWithMeta[] {
  return [createMessage('agent', WELCOME_MESSAGE)]
}

function createConversationRecord(): ConversationRecord {
  return {
    id: crypto.randomUUID(),
    title: 'Nouvelle conversation',
    titleEdited: false,
    updatedAt: new Date().toISOString(),
    messages: createWelcomeMessages()
  }
}

function normalizeMessage(message: MessageWithMeta): MessageWithMeta {
  return {
    role: message.role,
    content: message.content,
    createdAt: message.createdAt || new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }),
    sources: message.sources ?? [],
    client: message.client ?? null
  }
}

function conversationTitleFromMessages(items: MessageWithMeta[]): string {
  const firstVisitorMessage = items.find((item) => item.role === 'visitor' && item.content.trim())
  if (!firstVisitorMessage) return 'Nouvelle conversation'
  return firstVisitorMessage.content.trim().slice(0, 52) + (firstVisitorMessage.content.trim().length > 52 ? '...' : '')
}

function sortConversations(items: ConversationRecord[]): ConversationRecord[] {
  return [...items].sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
}

function buildErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    if (error.message === 'Failed to fetch') {
      return `Impossible de joindre l'API sur ${config.apiUrl}. Verifiez que le backend tourne et que SITE_ALLOWED_ORIGINS autorise cette origine.`
    }
    return error.message
  }
  return `Le service est indisponible. Verifiez que l'API est accessible sur ${config.apiUrl}.`
}

const isLoading = ref(false)
const draft = ref('')
const messages = ref<MessageWithMeta[]>(createWelcomeMessages())
const selectedSources = ref<SourceItem[]>([])
const selectedClient = ref<ClientItem | null>(null)
const appointmentToasts = ref<AppointmentNotification[]>([])
const pendingNootaToasts = ref<NootaPendingNotification[]>([])
const selectedPendingNoota = ref<NootaPendingNotification | null>(null)
const pendingNootaRecipientEmail = ref('')
const schedulingSuggestionKeys = ref<string[]>([])
const scheduledSuggestionKeys = ref<string[]>([])
const suggestionErrors = ref<Record<string, string>>({})
const driveStatus = ref<DriveStatus | null>(null)
const driveStatusLoading = ref(true)
const driveStatusError = ref('')
const conversations = ref<ConversationRecord[]>([])
const activeConversationId = ref('')
const importingPendingNootaIds = ref<string[]>([])
const hiddenPendingNootaIds = ref<string[]>([])
const knownAppointmentIds = new Set<string>()
const knownPendingNootaIds = new Set<string>()

let appointmentsPollTimer: number | undefined
let nootaReportsPollTimer: number | undefined
let driveStatusPollTimer: number | undefined
let pollingStarted = false

const canSend = computed(() => draft.value.trim().length > 0 && !isLoading.value)
const activeConversation = computed(() => conversations.value.find((item) => item.id === activeConversationId.value) ?? null)
const activeConversationTitle = computed(() => activeConversation.value?.title || config.title)
const hasSelectedSources = computed(() => selectedSources.value.length > 0)
const storageKey = computed(() => `agentia:conversations:${config.siteId || 'default'}:${config.clientId || 'all'}`)
const pendingNootaStorageKey = computed(() => `agentia:pending-noota:${config.siteId || 'default'}:${config.clientId || 'all'}`)
const hiddenPendingNootaStorageKey = computed(() => `agentia:hidden-pending-noota:${config.siteId || 'default'}:${config.clientId || 'all'}`)

function persistConversations() {
  localStorage.setItem(storageKey.value, JSON.stringify(conversations.value))
}

function persistPendingNootaToasts() {
  localStorage.setItem(pendingNootaStorageKey.value, JSON.stringify(pendingNootaToasts.value))
}

function persistHiddenPendingNootaIds() {
  localStorage.setItem(hiddenPendingNootaStorageKey.value, JSON.stringify(hiddenPendingNootaIds.value))
}

function syncActiveConversation() {
  if (!activeConversationId.value) return

  const existing = conversations.value.find((item) => item.id === activeConversationId.value)
  const record: ConversationRecord = {
    id: activeConversationId.value,
    title: existing?.titleEdited ? existing.title || 'Nouvelle conversation' : conversationTitleFromMessages(messages.value),
    titleEdited: existing?.titleEdited ?? false,
    updatedAt: new Date().toISOString(),
    messages: messages.value.map(normalizeMessage)
  }

  const next = conversations.value.filter((item) => item.id !== record.id)
  conversations.value = sortConversations([record, ...next])
  persistConversations()
}

function loadConversations() {
  const raw = localStorage.getItem(storageKey.value)
  if (!raw) {
    const firstConversation = createConversationRecord()
    conversations.value = [firstConversation]
    activeConversationId.value = firstConversation.id
    messages.value = firstConversation.messages.map(normalizeMessage)
    persistConversations()
    return
  }

  try {
    const parsed = JSON.parse(raw) as ConversationRecord[]
    const sanitized = parsed
      .filter((item) => item && typeof item.id === 'string' && Array.isArray(item.messages))
      .map((item) => ({
        id: item.id,
        title: item.title || 'Nouvelle conversation',
        titleEdited: Boolean(item.titleEdited),
        updatedAt: item.updatedAt || new Date().toISOString(),
        messages: item.messages.length ? item.messages.map(normalizeMessage) : createWelcomeMessages()
      }))

    if (!sanitized.length) {
      const firstConversation = createConversationRecord()
      conversations.value = [firstConversation]
      activeConversationId.value = firstConversation.id
      messages.value = firstConversation.messages.map(normalizeMessage)
      persistConversations()
      return
    }

    conversations.value = sortConversations(sanitized)
    activeConversationId.value = conversations.value[0].id
    messages.value = conversations.value[0].messages.map(normalizeMessage)
  } catch {
    const firstConversation = createConversationRecord()
    conversations.value = [firstConversation]
    activeConversationId.value = firstConversation.id
    messages.value = firstConversation.messages.map(normalizeMessage)
    persistConversations()
  }
}

function loadPendingNootaToasts() {
  const raw = localStorage.getItem(pendingNootaStorageKey.value)
  if (!raw) return

  try {
    const parsed = JSON.parse(raw) as NootaPendingNotification[]
    pendingNootaToasts.value = parsed
      .filter((item) => item && typeof item.external_id === 'string')
      .map((item) => ({
        ...item,
        suggested_appointments: Array.isArray(item.suggested_appointments) ? item.suggested_appointments : []
      }))

    for (const item of pendingNootaToasts.value) {
      knownPendingNootaIds.add(item.external_id)
    }
  } catch {
    pendingNootaToasts.value = []
  }
}

function loadHiddenPendingNootaIds() {
  const raw = localStorage.getItem(hiddenPendingNootaStorageKey.value)
  if (!raw) return

  try {
    const parsed = JSON.parse(raw) as string[]
    hiddenPendingNootaIds.value = parsed.filter((item) => typeof item === 'string')
  } catch {
    hiddenPendingNootaIds.value = []
  }
}

function markPendingNootaAsHidden(externalId: string) {
  if (hiddenPendingNootaIds.value.includes(externalId)) return
  hiddenPendingNootaIds.value = [...hiddenPendingNootaIds.value, externalId]
  persistHiddenPendingNootaIds()
}

function startNewConversation() {
  const record = createConversationRecord()
  conversations.value = sortConversations([record, ...conversations.value])
  activeConversationId.value = record.id
  messages.value = record.messages.map(normalizeMessage)
  selectedSources.value = []
  selectedClient.value = null
  draft.value = ''
  persistConversations()
}

function openConversation(id: string) {
  const record = conversations.value.find((item) => item.id === id)
  if (!record) return
  activeConversationId.value = id
  messages.value = record.messages.map(normalizeMessage)
  selectedSources.value = []
  selectedClient.value = null
  draft.value = ''
}

function deleteConversation(id: string) {
  const next = conversations.value.filter((item) => item.id !== id)
  if (!next.length) {
    const record = createConversationRecord()
    conversations.value = [record]
    activeConversationId.value = record.id
    messages.value = record.messages.map(normalizeMessage)
    selectedSources.value = []
    selectedClient.value = null
    persistConversations()
    return
  }

  conversations.value = sortConversations(next)
  if (activeConversationId.value === id) {
    activeConversationId.value = conversations.value[0].id
    messages.value = conversations.value[0].messages.map(normalizeMessage)
    selectedSources.value = []
    selectedClient.value = null
  }
  persistConversations()
}

function renameConversation(id: string, title: string) {
  conversations.value = sortConversations(
    conversations.value.map((item) =>
      item.id === id
        ? {
            ...item,
            title: title.trim() || 'Nouvelle conversation',
            titleEdited: true
          }
        : item
    )
  )
  persistConversations()
}

function openSourcesForMessage(message: MessageWithMeta) {
  selectedSources.value = message.sources ?? []
  selectedClient.value = message.client ?? null
}

function dismissToast(id: string) {
  appointmentToasts.value = appointmentToasts.value.filter((item) => item.id !== id)
}

function pushAppointmentToast(notification: AppointmentNotification) {
  appointmentToasts.value = [notification, ...appointmentToasts.value.filter((item) => item.id !== notification.id)].slice(0, 4)
  window.setTimeout(() => dismissToast(notification.id), 8000)
}

function suggestionKey(externalId: string, suggestion: SuggestedAppointment): string {
  return `${externalId}:${suggestion.start}:${suggestion.title}`
}

function openPendingNootaPreview(notification: NootaPendingNotification) {
  selectedPendingNoota.value = notification
  pendingNootaRecipientEmail.value = ''
}

function closePendingNootaPreview() {
  selectedPendingNoota.value = null
  pendingNootaRecipientEmail.value = ''
}

function dismissPendingNootaToast(externalId: string) {
  markPendingNootaAsHidden(externalId)
  pendingNootaToasts.value = pendingNootaToasts.value.filter((item) => item.external_id !== externalId)
  if (selectedPendingNoota.value?.external_id === externalId) {
    closePendingNootaPreview()
  }
  persistPendingNootaToasts()
}

async function schedulePendingNootaSuggestion(notification: NootaPendingNotification, suggestion: SuggestedAppointment) {
  const key = suggestionKey(notification.external_id, suggestion)
  if (schedulingSuggestionKeys.value.includes(key) || scheduledSuggestionKeys.value.includes(key)) return

  suggestionErrors.value = { ...suggestionErrors.value, [key]: '' }
  schedulingSuggestionKeys.value = [...schedulingSuggestionKeys.value, key]

  try {
    if (config.demoMailFlow) {
      scheduledSuggestionKeys.value = [...scheduledSuggestionKeys.value, key]
      pushAppointmentToast({
        id: crypto.randomUUID(),
        site_id: config.siteId,
        client_name: notification.client_name,
        client_email: '',
        scheduled_for: suggestion.start,
        timezone: suggestion.timezone,
        created_at: new Date().toISOString(),
        html_link: null
      })
      messages.value.push(
        createMessage(
          'agent',
          `Rendez-vous propose ajoute en mode maquette : ${suggestion.title}, le ${formatDateTimeWithTimezone(suggestion.start, suggestion.timezone)} (${suggestion.timezone}).`
        )
      )
      syncActiveConversation()
      return
    }

    const response = await fetch(`${apiBaseUrl}/integrations/noota/google-drive/schedule-suggestion`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        site_id: config.siteId,
        external_id: notification.external_id,
        title: suggestion.title,
        start: suggestion.start,
        end: suggestion.end,
        timezone: suggestion.timezone,
        description: suggestion.source_excerpt
      })
    })

    if (!response.ok) {
      let detail = ''
      try {
        const payload = await response.json()
        if (typeof payload?.detail === 'string' && payload.detail.trim()) {
          detail = payload.detail.trim()
        }
      } catch {
        detail = ''
      }
      throw new Error(detail || "Impossible d'ajouter le rendez-vous a l'agenda.")
    }

    const created = (await response.json()) as ScheduledSuggestionResponse
    scheduledSuggestionKeys.value = [...scheduledSuggestionKeys.value, key]
    suggestionErrors.value = { ...suggestionErrors.value, [key]: '' }
    pushAppointmentToast({
      id: created.notification_id || created.event_id,
      site_id: config.siteId,
      client_name: notification.client_name,
      client_email: '',
      scheduled_for: created.start,
      timezone: created.timezone,
      created_at: new Date().toISOString(),
      html_link: created.html_link ?? null
    })
    if (created.notification_id) {
      knownAppointmentIds.add(created.notification_id)
    }
    messages.value.push(
      createMessage(
        'agent',
        `Rendez-vous ajoute a l'agenda : ${created.title}, le ${formatDateTimeWithTimezone(created.start, created.timezone)} (${created.timezone}).`
      )
    )
    syncActiveConversation()
  } catch (error) {
    suggestionErrors.value = { ...suggestionErrors.value, [key]: buildErrorMessage(error) }
    messages.value.push(createMessage('agent', buildErrorMessage(error)))
    syncActiveConversation()
  } finally {
    schedulingSuggestionKeys.value = schedulingSuggestionKeys.value.filter((item) => item !== key)
  }
}

async function syncAppointmentNotifications(seedOnly = false) {
  if (!config.siteId) return

  try {
    const response = await fetch(`${apiBaseUrl}/appointments/recent?site_id=${encodeURIComponent(config.siteId)}&limit=5`)
    if (!response.ok) return

    const payload = (await response.json()) as { items?: AppointmentNotification[] }
    const items = payload.items ?? []
    const unseen = items.filter((item) => !knownAppointmentIds.has(item.id))

    for (const item of items) {
      knownAppointmentIds.add(item.id)
    }

    if (!seedOnly) {
      unseen.reverse().forEach(pushAppointmentToast)
    }
  } catch {
    // Keep the application usable if notification polling fails.
  }
}

async function syncPendingNootaReports() {
  if (!config.siteId) return

  try {
    const response = await fetch(
      `${apiBaseUrl}/integrations/noota/google-drive/pending?site_id=${encodeURIComponent(config.siteId)}&limit=5`
    )
    if (!response.ok) return

    const payload = (await response.json()) as { items?: NootaPendingNotification[] }
    const hiddenIds = new Set(hiddenPendingNootaIds.value)
    const items = (payload.items ?? []).filter((item) => !hiddenIds.has(item.external_id))

    for (const item of items) {
      knownPendingNootaIds.add(item.external_id)
    }

    pendingNootaToasts.value = items.map((item) => ({
      ...item,
      suggested_appointments: Array.isArray(item.suggested_appointments) ? item.suggested_appointments : []
    }))
    persistPendingNootaToasts()
  } catch {
    // Keep the application usable if Drive polling fails.
  }
}

async function syncDriveStatus() {
  if (!config.siteId) return

  driveStatusLoading.value = true
  driveStatusError.value = ''

  try {
    const response = await fetch(`${apiBaseUrl}/integrations/noota/google-drive/status?site_id=${encodeURIComponent(config.siteId)}&limit=5`)
    if (!response.ok) {
      let detail = ''
      try {
        const payload = await response.json()
        if (typeof payload?.detail === 'string' && payload.detail.trim()) {
          detail = payload.detail.trim()
        }
      } catch {
        detail = ''
      }
      driveStatus.value = null
      driveStatusError.value = detail || `Etat Drive indisponible (${response.status}).`
      return
    }
    driveStatus.value = (await response.json()) as DriveStatus
  } catch {
    driveStatus.value = null
    driveStatusError.value = `Impossible de joindre l'API sur ${config.apiUrl}.`
  } finally {
    driveStatusLoading.value = false
  }
}

async function importPendingNootaReport(notification: NootaPendingNotification) {
  if (importingPendingNootaIds.value.includes(notification.external_id)) return

  importingPendingNootaIds.value = [...importingPendingNootaIds.value, notification.external_id]

  try {
    if (config.demoMailFlow) {
      markPendingNootaAsHidden(notification.external_id)
      pendingNootaToasts.value = pendingNootaToasts.value.filter((item) => item.external_id !== notification.external_id)
      persistPendingNootaToasts()
      closePendingNootaPreview()
      messages.value.push(
        createMessage(
          'agent',
          `Maquette validee : le compte rendu "${notification.meeting_title}" serait remis en forme, ajoute a la base puis envoye a ${pendingNootaRecipientEmail.value.trim()}.`
        )
      )
      syncActiveConversation()
      return
    }

    const response = await fetch(`${apiBaseUrl}/integrations/noota/google-drive/import-and-email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        site_id: config.siteId,
        external_id: notification.external_id,
        recipient_email: pendingNootaRecipientEmail.value.trim()
      })
    })

    if (!response.ok) {
      let detail = ''
      try {
        const payload = await response.json()
        if (typeof payload?.detail === 'string' && payload.detail.trim()) {
          detail = payload.detail.trim()
        }
      } catch {
        detail = ''
      }
      throw new Error(detail || "Impossible d'importer le compte rendu.")
    }

    const imported = (await response.json()) as ImportAndEmailResponse
    markPendingNootaAsHidden(notification.external_id)
    pendingNootaToasts.value = pendingNootaToasts.value.filter((item) => item.external_id !== notification.external_id)
    persistPendingNootaToasts()
    closePendingNootaPreview()

    for (const appointment of imported.scheduled_appointments ?? []) {
      pushAppointmentToast({
        id: appointment.notification_id || appointment.event_id,
        site_id: config.siteId,
        client_name: notification.client_name,
        client_email: '',
        scheduled_for: appointment.start,
        timezone: appointment.timezone,
        created_at: new Date().toISOString(),
        html_link: appointment.html_link ?? null
      })
      if (appointment.notification_id) {
        knownAppointmentIds.add(appointment.notification_id)
      }
    }

    const scheduledCount = imported.scheduled_appointments?.length ?? 0
    messages.value.push(
      createMessage(
        'agent',
        scheduledCount > 0
          ? `Compte rendu importe, remis en forme et envoye par mail : ${notification.meeting_title}. ${scheduledCount} rendez-vous ont aussi ete ajoutes a l'agenda.`
          : `Compte rendu importe, remis en forme et envoye par mail : ${notification.meeting_title}.`
      )
    )
    syncActiveConversation()
  } catch (error) {
    messages.value.push(createMessage('agent', buildErrorMessage(error)))
    syncActiveConversation()
  } finally {
    importingPendingNootaIds.value = importingPendingNootaIds.value.filter((item) => item !== notification.external_id)
  }
}

async function sendMessage(prefilledMessage?: string) {
  const message = prepareOutgoingMessage(prefilledMessage ?? draft.value)
  if (!message || isLoading.value) return

  const history = buildRequestHistory(messages.value)
  messages.value.push(createMessage('visitor', message))
  draft.value = ''
  isLoading.value = true
  syncActiveConversation()

  try {
    const response = await fetch(`${apiBaseUrl}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        site_id: config.siteId,
        client_id: config.clientId,
        message,
        history
      })
    })

    if (!response.ok) {
      let detail = ''
      try {
        const payload = await response.json()
        if (typeof payload?.detail === 'string' && payload.detail.trim()) {
          detail = payload.detail.trim()
        }
      } catch {
        detail = ''
      }

      if (response.status === 403) {
        throw new Error("Acces refuse par l'API. Verifiez SITE_ALLOWED_ORIGINS.")
      }
      if (response.status === 429) {
        throw new Error('Trop de requetes. Reessayez dans une minute.')
      }
      if (response.status >= 500) {
        throw new Error(detail || "L'API a rencontre une erreur interne.")
      }
      throw new Error(detail || `La requete a echoue (${response.status}).`)
    }

    const data = (await response.json()) as ChatResponse
    messages.value.push(
      createMessage('agent', data.answer, {
        sources: data.sources ?? [],
        client: data.client ?? null
      })
    )
  } catch (error) {
    messages.value.push(createMessage('agent', buildErrorMessage(error)))
  } finally {
    isLoading.value = false
    syncActiveConversation()
  }
}

async function refreshDriveMonitoring() {
  await Promise.all([syncDriveStatus(), syncPendingNootaReports()])
}

async function startPolling() {
  if (pollingStarted) return
  pollingStarted = true

  loadConversations()
  loadHiddenPendingNootaIds()
  loadPendingNootaToasts()
  await syncDriveStatus()
  await syncPendingNootaReports()
  await syncAppointmentNotifications(true)

  appointmentsPollTimer = window.setInterval(() => {
    void syncAppointmentNotifications(false)
  }, 10000)
  nootaReportsPollTimer = window.setInterval(() => {
    void syncPendingNootaReports()
  }, 15000)
  driveStatusPollTimer = window.setInterval(() => {
    void syncDriveStatus()
  }, 15000)
}

function stopPolling() {
  if (appointmentsPollTimer) {
    window.clearInterval(appointmentsPollTimer)
  }
  if (nootaReportsPollTimer) {
    window.clearInterval(nootaReportsPollTimer)
  }
  if (driveStatusPollTimer) {
    window.clearInterval(driveStatusPollTimer)
  }
  appointmentsPollTimer = undefined
  nootaReportsPollTimer = undefined
  driveStatusPollTimer = undefined
  pollingStarted = false
}

export function formatConversationDate(value: string): string {
  return new Intl.DateTimeFormat('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(new Date(value))
}

export function formatAppointmentDate(value: string, timezone: string): string {
  return new Intl.DateTimeFormat('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: timezone
  }).format(new Date(value))
}

export function formatDateTimeWithTimezone(value: string, timezone: string): string {
  return new Intl.DateTimeFormat('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: timezone
  }).format(new Date(value))
}

const agentiaState = {
  config,
  isLoading,
  draft,
  messages,
  selectedSources,
  selectedClient,
  appointmentToasts,
  pendingNootaToasts,
  selectedPendingNoota,
  pendingNootaRecipientEmail,
  schedulingSuggestionKeys,
  scheduledSuggestionKeys,
  suggestionErrors,
  driveStatus,
  driveStatusLoading,
  driveStatusError,
  conversations,
  activeConversationId,
  importingPendingNootaIds,
  canSend,
  activeConversation,
  activeConversationTitle,
  hasSelectedSources,
  startNewConversation,
  openConversation,
  deleteConversation,
  renameConversation,
  openSourcesForMessage,
  dismissToast,
  suggestionKey,
  openPendingNootaPreview,
  closePendingNootaPreview,
  dismissPendingNootaToast,
  schedulePendingNootaSuggestion,
  importPendingNootaReport,
  sendMessage,
  syncDriveStatus,
  syncPendingNootaReports,
  refreshDriveMonitoring,
  startPolling,
  stopPolling
}

export function useAgentiaState() {
  return agentiaState
}
