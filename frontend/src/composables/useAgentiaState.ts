import { computed, ref } from 'vue'
import { buildRequestHistory, prepareOutgoingMessage, WELCOME_MESSAGE } from '../chatPayload'
import { getAppConfig } from '../config'
import type {
  AppointmentNotification,
  ClientArtifact,
  ClientEvent,
  ChatResponse,
  ClientCreatePayload,
  ClientItem,
  ClientProject,
  ClientProjectTask,
  ClientProjectTaskStatus,
  ClientUpdatePayload,
  ConversationRecord,
  DriveStatus,
  ImportAndEmailResponse,
  MessageWithMeta,
  NootaPendingNotification,
  OfferAssistantResponse,
  OfferMissingItem,
  OfferProjectContext,
  OfferProjectEmailSummary,
  OfferProjectExportSummary,
  OfferProjectFileSummary,
  OfferProjectSummary,
  OfferTaskChoice,
  OfferTaskChoiceDecision,
  OfferReferenceSummary,
  RewriteReportResponse,
  ScheduledSuggestionResponse,
  SourceItem,
  SuggestedAppointment,
  SuggestedTask,
  TeamProfileSummary
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
const clients = ref<ClientItem[]>([])
const clientTasks = ref<Record<string, ClientProjectTask[]>>({})
const clientTasksLoading = ref<Record<string, boolean>>({})
const clientsLoading = ref(false)
const clientsError = ref('')
const appointmentToasts = ref<AppointmentNotification[]>([])
const pendingNootaToasts = ref<NootaPendingNotification[]>([])
const pendingNootaReports = ref<NootaPendingNotification[]>([])
const selectedPendingNoota = ref<NootaPendingNotification | null>(null)
const pendingNootaRecipientEmail = ref('')
const pendingNootaClientName = ref('')
const selectedPendingNootaTaskKeys = ref<string[]>([])
const schedulingSuggestionKeys = ref<string[]>([])
const scheduledSuggestionKeys = ref<string[]>([])
const suggestionErrors = ref<Record<string, string>>({})
const driveStatus = ref<DriveStatus | null>(null)
const driveStatusLoading = ref(true)
const driveStatusError = ref('')
const conversations = ref<ConversationRecord[]>([])
const activeConversationId = ref('')
const offerProjects = ref<OfferProjectSummary[]>([])
const activeOfferProjectId = ref('')
const offerProjectMessages = ref<MessageWithMeta[]>([])
const offerProjectDraft = ref('')
const isOfferProjectLoading = ref(false)
const offerProjectMissingItems = ref<OfferMissingItem[]>([])
const offerProjectEmails = ref<OfferProjectEmailSummary[]>([])
const offerProjectFiles = ref<OfferProjectFileSummary[]>([])
const offerProjectReferences = ref<OfferReferenceSummary[]>([])
const offerProjectTeamProfiles = ref<TeamProfileSummary[]>([])
const offerProjectExports = ref<OfferProjectExportSummary[]>([])
const offerLinkedClient = ref<ClientItem | null>(null)
const offerLinkedClientProject = ref<ClientProject | null>(null)
const offerClientArtifacts = ref<ClientArtifact[]>([])
const offerClientRecentEvents = ref<ClientEvent[]>([])
const offerClientProjectTasks = ref<ClientProjectTask[]>([])
const offerTaskChoices = ref<OfferTaskChoice[]>([])
const generatedOfferMarkdown = ref('')
const offerProjectTitle = ref('')
const offerProjectClientName = ref('')
const offerProjectSector = ref('')
const offerProjectRequestSummary = ref('')
const offerProjectScopeDetails = ref('')
const offerProjectDeliverables = ref('')
const offerProjectPlanningDetails = ref('')
const offerProjectPricingDetails = ref('')
const offerProjectTimeSpentDetails = ref('')
const offerProjectTeamDetails = ref('')
const offerProjectConstraints = ref('')
const offerProjectEmailDraft = ref('')
const offerProjectEmailSubject = ref('')
const offerProjectEmailSender = ref('')
const offerProjectSelectedFiles = ref<File[]>([])
const isOfferProjectGenerating = ref(false)
const isOfferProjectEmailSubmitting = ref(false)
const isOfferProjectSavingConfig = ref(false)
const isOfferProjectUploadingFiles = ref(false)
const isOfferTaskChoicesSaving = ref(false)
const importingPendingNootaIds = ref<string[]>([])
const reformulatingPendingNootaIds = ref<string[]>([])
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
const activeOfferProject = computed(() => offerProjects.value.find((item) => item.id === activeOfferProjectId.value) ?? null)
const activeOfferProjectTitle = computed(() => activeOfferProject.value?.title || "Proposition d'offre")
const canSendOfferProjectMessage = computed(() => offerProjectDraft.value.trim().length > 0 && !isOfferProjectLoading.value)
const activeOfferProjectCompletionRatio = computed(() => activeOfferProject.value?.completion_ratio ?? 0)

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

function normalizeOfferProjectMessage(message: { role: 'visitor' | 'agent'; content: string; created_at: string }): MessageWithMeta {
  return {
    role: message.role,
    content: message.content,
    createdAt: formatConversationTime(message.created_at),
    sources: [],
    client: null
  }
}

function formatConversationTime(value: string): string {
  try {
    return new Intl.DateTimeFormat('fr-FR', {
      hour: '2-digit',
      minute: '2-digit'
    }).format(new Date(value))
  } catch {
    return new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
  }
}

function applyOfferProjectContext(context: OfferProjectContext) {
  const existingIndex = offerProjects.value.findIndex((item) => item.id === context.project.id)
  if (existingIndex >= 0) {
    offerProjects.value = [
      ...offerProjects.value.slice(0, existingIndex),
      context.project,
      ...offerProjects.value.slice(existingIndex + 1)
    ].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
  } else {
    offerProjects.value = [context.project, ...offerProjects.value].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
  }
  activeOfferProjectId.value = context.project.id
  offerProjectMessages.value = context.messages.map(normalizeOfferProjectMessage)
  offerProjectMissingItems.value = context.missing_items
  offerProjectEmails.value = context.emails
  offerProjectFiles.value = context.files
  offerProjectReferences.value = context.references
  offerProjectTeamProfiles.value = context.suggested_team_profiles
  offerProjectExports.value = context.exports
  offerLinkedClient.value = context.linked_client ?? null
  offerLinkedClientProject.value = context.linked_client_project ?? null
  offerClientArtifacts.value = context.client_artifacts ?? []
  offerClientRecentEvents.value = context.client_recent_events ?? []
  offerClientProjectTasks.value = context.client_project_tasks ?? []
  offerTaskChoices.value = context.task_choices ?? []
  generatedOfferMarkdown.value = context.generated_offer_markdown
  offerProjectTitle.value = context.project.title
  offerProjectClientName.value = context.project.client_name
  offerProjectSector.value = context.project.sector
  offerProjectRequestSummary.value = context.request_summary
  offerProjectScopeDetails.value = context.scope_details
  offerProjectDeliverables.value = context.deliverables
  offerProjectPlanningDetails.value = context.planning_details
  offerProjectPricingDetails.value = context.pricing_details
  offerProjectTimeSpentDetails.value = context.time_spent_details
  offerProjectTeamDetails.value = context.team_details
  offerProjectConstraints.value = context.constraints
}

async function loadOfferProjects() {
  if (!config.siteId) return
  const response = await fetch(`${apiBaseUrl}/offers/projects?site_id=${encodeURIComponent(config.siteId)}`)
  if (!response.ok) {
    throw new Error('Impossible de charger les projets d’offre.')
  }
  offerProjects.value = ((await response.json()) as OfferProjectSummary[]).sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
  if (!offerProjects.value.length) {
    const created = await createOfferProject()
    activeOfferProjectId.value = created.id
    await refreshOfferProjectContext(created.id)
    return
  }
  activeOfferProjectId.value = activeOfferProjectId.value || offerProjects.value[0].id
  await refreshOfferProjectContext(activeOfferProjectId.value)
}

function buildAdminHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (config.adminApiToken) {
    headers['X-Admin-Token'] = config.adminApiToken
  }
  return headers
}

async function loadClients() {
  if (!config.siteId) return
  clientsLoading.value = true
  clientsError.value = ''

  try {
    const response = await fetch(`${apiBaseUrl}/clients?site_id=${encodeURIComponent(config.siteId)}`)
    if (!response.ok) {
      throw new Error('Impossible de charger les clients.')
    }
    clients.value = (await response.json()) as ClientItem[]
  } catch (error) {
    clientsError.value = buildErrorMessage(error)
  } finally {
    clientsLoading.value = false
  }
}

async function loadClientTasks(clientId: string) {
  if (!config.siteId || !clientId) return []
  clientTasksLoading.value = { ...clientTasksLoading.value, [clientId]: true }
  clientsError.value = ''

  try {
    const response = await fetch(`${apiBaseUrl}/clients/${clientId}/tasks?site_id=${encodeURIComponent(config.siteId)}`)
    if (!response.ok) {
      throw new Error('Impossible de charger les taches du client.')
    }
    const tasks = (await response.json()) as ClientProjectTask[]
    clientTasks.value = { ...clientTasks.value, [clientId]: tasks }
    return tasks
  } catch (error) {
    clientsError.value = buildErrorMessage(error)
    return []
  } finally {
    clientTasksLoading.value = { ...clientTasksLoading.value, [clientId]: false }
  }
}

async function suggestClientTasks(clientId: string) {
  if (!config.siteId || !clientId) return []
  clientTasksLoading.value = { ...clientTasksLoading.value, [clientId]: true }
  clientsError.value = ''

  try {
    const response = await fetch(`${apiBaseUrl}/clients/${clientId}/tasks/suggest?site_id=${encodeURIComponent(config.siteId)}`, {
      method: 'POST'
    })
    if (!response.ok) {
      throw new Error("Impossible d'extraire les taches des comptes rendus.")
    }
    const tasks = (await response.json()) as ClientProjectTask[]
    clientTasks.value = { ...clientTasks.value, [clientId]: tasks }
    return tasks
  } catch (error) {
    clientsError.value = buildErrorMessage(error)
    return []
  } finally {
    clientTasksLoading.value = { ...clientTasksLoading.value, [clientId]: false }
  }
}

async function updateClientTaskStatus(taskId: string, status: ClientProjectTaskStatus) {
  if (!config.siteId || !taskId) return null
  clientsError.value = ''

  try {
    const response = await fetch(`${apiBaseUrl}/clients/tasks/${taskId}?site_id=${encodeURIComponent(config.siteId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status })
    })
    if (!response.ok) {
      throw new Error('Impossible de classer la tache.')
    }
    const updated = (await response.json()) as ClientProjectTask
    const existing = clientTasks.value[updated.client_id] ?? []
    clientTasks.value = {
      ...clientTasks.value,
      [updated.client_id]: existing.map((item) => (item.id === updated.id ? updated : item))
    }
    return updated
  } catch (error) {
    clientsError.value = buildErrorMessage(error)
    return null
  }
}

async function createClient(payload: ClientCreatePayload) {
  clientsError.value = ''
  const response = await fetch(`${apiBaseUrl}/clients`, {
    method: 'POST',
    headers: buildAdminHeaders(),
    body: JSON.stringify({
      ...payload,
      site_id: payload.site_id || config.siteId
    })
  })

  if (!response.ok) {
    clientsError.value =
      response.status === 401
        ? 'Token admin manquant ou invalide pour creer un client.'
        : 'Impossible de creer le client en base.'
    throw new Error(clientsError.value)
  }

  const created = (await response.json()) as ClientItem
  clients.value = [created, ...clients.value.filter((item) => item.id !== created.id)]
  return created
}

async function updateClient(clientId: string, payload: ClientUpdatePayload) {
  clientsError.value = ''
  const response = await fetch(`${apiBaseUrl}/clients/${clientId}`, {
    method: 'PATCH',
    headers: buildAdminHeaders(),
    body: JSON.stringify(payload)
  })

  if (!response.ok) {
    clientsError.value =
      response.status === 401
        ? 'Token admin manquant ou invalide pour modifier le client.'
        : response.status === 404
          ? 'Client introuvable en base.'
          : 'Impossible de modifier le client.'
    throw new Error(clientsError.value)
  }

  const updated = (await response.json()) as ClientItem
  clients.value = clients.value.map((item) => (item.id === updated.id ? updated : item))
  return updated
}

async function deleteClient(clientId: string) {
  clientsError.value = ''
  const response = await fetch(`${apiBaseUrl}/clients/${clientId}`, {
    method: 'DELETE',
    headers: buildAdminHeaders()
  })

  if (!response.ok) {
    clientsError.value =
      response.status === 401
        ? 'Token admin manquant ou invalide pour supprimer le client.'
        : response.status === 404
          ? 'Client introuvable en base.'
          : 'Impossible de supprimer le client.'
    throw new Error(clientsError.value)
  }

  clients.value = clients.value.filter((item) => item.id !== clientId)
}

async function refreshOfferProjectContext(projectId = activeOfferProjectId.value) {
  if (!projectId || !config.siteId) return
  const response = await fetch(`${apiBaseUrl}/offers/projects/${projectId}/context?site_id=${encodeURIComponent(config.siteId)}`)
  if (!response.ok) {
    throw new Error('Impossible de charger le contexte du projet d’offre.')
  }
  applyOfferProjectContext((await response.json()) as OfferProjectContext)
}

async function createOfferProject() {
  const response = await fetch(`${apiBaseUrl}/offers/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ site_id: config.siteId, title: "Nouveau projet d'offre" })
  })
  if (!response.ok) {
    throw new Error('Impossible de creer le projet d’offre.')
  }
  return (await response.json()) as OfferProjectSummary
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
        suggested_appointments: Array.isArray(item.suggested_appointments) ? item.suggested_appointments : [],
        suggested_tasks: Array.isArray(item.suggested_tasks) ? item.suggested_tasks : []
      }))
    pendingNootaReports.value = pendingNootaToasts.value

    for (const item of pendingNootaToasts.value) {
      knownPendingNootaIds.add(item.external_id)
    }
  } catch {
    pendingNootaToasts.value = []
    pendingNootaReports.value = []
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

async function startNewOfferProject() {
  const created = await createOfferProject()
  activeOfferProjectId.value = created.id
  offerProjectDraft.value = ''
  await refreshOfferProjectContext(created.id)
}

async function openOfferProject(id: string) {
  activeOfferProjectId.value = id
  offerProjectDraft.value = ''
  await refreshOfferProjectContext(id)
}

async function deleteOfferProject(id: string) {
  const response = await fetch(`${apiBaseUrl}/offers/projects/${id}`, {
    method: 'DELETE'
  })
  if (!response.ok) {
    throw new Error('Impossible de supprimer le projet d’offre.')
  }
  offerProjects.value = offerProjects.value.filter((item) => item.id !== id)
  if (!offerProjects.value.length) {
    await startNewOfferProject()
    return
  }
  if (activeOfferProjectId.value === id) {
    await openOfferProject(offerProjects.value[0].id)
  }
}

async function renameOfferProject(id: string, title: string) {
  const response = await fetch(`${apiBaseUrl}/offers/projects/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title })
  })
  if (!response.ok) {
    throw new Error('Impossible de renommer le projet d’offre.')
  }
  const updated = (await response.json()) as OfferProjectSummary
  offerProjects.value = offerProjects.value
    .map((item) => (item.id === id ? updated : item))
    .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
}

async function saveOfferProjectConfig() {
  if (!activeOfferProjectId.value || isOfferProjectSavingConfig.value) return
  isOfferProjectSavingConfig.value = true
  try {
    const response = await fetch(`${apiBaseUrl}/offers/projects/${activeOfferProjectId.value}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        client_name: offerProjectClientName.value,
        sector: offerProjectSector.value,
        title: offerProjectTitle.value,
        request_summary: offerProjectRequestSummary.value,
        scope_details: offerProjectScopeDetails.value,
        deliverables: offerProjectDeliverables.value,
        planning_details: offerProjectPlanningDetails.value,
        pricing_details: offerProjectPricingDetails.value,
        time_spent_details: offerProjectTimeSpentDetails.value,
        team_details: offerProjectTeamDetails.value,
        constraints: offerProjectConstraints.value
      })
    })
    if (!response.ok) {
      throw new Error("Impossible d'enregistrer la configuration du projet.")
    }
    const updated = (await response.json()) as OfferProjectSummary
    offerProjects.value = offerProjects.value
      .map((item) => (item.id === updated.id ? updated : item))
      .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
    await refreshOfferProjectContext(updated.id)
  } finally {
    isOfferProjectSavingConfig.value = false
  }
}

function setOfferProjectSelectedFiles(files: FileList | null) {
  offerProjectSelectedFiles.value = files ? Array.from(files) : []
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

function taskSuggestionKey(task: SuggestedTask): string {
  if (task.key?.trim()) return task.key
  return [task.title, task.owner ?? '', task.due_date ?? '']
    .map((part) => part.trim().toLowerCase().replace(/\s+/g, ' '))
    .join('|')
}

function openPendingNootaPreview(notification: NootaPendingNotification) {
  selectedPendingNoota.value = notification
  pendingNootaRecipientEmail.value = ''
  pendingNootaClientName.value = notification.client_name
  selectedPendingNootaTaskKeys.value = (notification.suggested_tasks ?? []).map(taskSuggestionKey)
}

function closePendingNootaPreview() {
  selectedPendingNoota.value = null
  pendingNootaRecipientEmail.value = ''
  pendingNootaClientName.value = ''
  selectedPendingNootaTaskKeys.value = []
}

function togglePendingNootaTask(task: SuggestedTask) {
  const key = taskSuggestionKey(task)
  selectedPendingNootaTaskKeys.value = selectedPendingNootaTaskKeys.value.includes(key)
    ? selectedPendingNootaTaskKeys.value.filter((item) => item !== key)
    : [...selectedPendingNootaTaskKeys.value, key]
}

function updatePendingNootaReport(externalId: string, formattedReport: string) {
  pendingNootaReports.value = pendingNootaReports.value.map((item) =>
    item.external_id === externalId
      ? {
          ...item,
          formatted_report: formattedReport
        }
      : item
  )
  pendingNootaToasts.value = pendingNootaToasts.value.map((item) =>
    item.external_id === externalId
      ? {
          ...item,
          formatted_report: formattedReport
        }
      : item
  )

  if (selectedPendingNoota.value?.external_id === externalId) {
    selectedPendingNoota.value = {
      ...selectedPendingNoota.value,
      formatted_report: formattedReport
    }
  }

  persistPendingNootaToasts()
}

function updatePendingNootaClientName(externalId: string, clientName: string) {
  const normalizedClientName = clientName.trimStart()
  pendingNootaReports.value = pendingNootaReports.value.map((item) =>
    item.external_id === externalId
      ? {
          ...item,
          client_name: normalizedClientName
        }
      : item
  )
  pendingNootaToasts.value = pendingNootaToasts.value.map((item) =>
    item.external_id === externalId
      ? {
          ...item,
          client_name: normalizedClientName
        }
      : item
  )

  if (selectedPendingNoota.value?.external_id === externalId) {
    selectedPendingNoota.value = {
      ...selectedPendingNoota.value,
      client_name: normalizedClientName
    }
  }

  pendingNootaClientName.value = normalizedClientName
  persistPendingNootaToasts()
}

function dismissPendingNootaToast(externalId: string) {
  markPendingNootaAsHidden(externalId)
  pendingNootaToasts.value = pendingNootaToasts.value.filter((item) => item.external_id !== externalId)
  pendingNootaReports.value = pendingNootaReports.value.filter((item) => item.external_id !== externalId)
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
        client_name: pendingNootaClientName.value.trim() || notification.client_name,
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
        client_name: pendingNootaClientName.value.trim(),
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
      client_name: pendingNootaClientName.value.trim() || notification.client_name,
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

async function reformulatePendingNootaReport(notification: NootaPendingNotification) {
  if (reformulatingPendingNootaIds.value.includes(notification.external_id)) return

  reformulatingPendingNootaIds.value = [...reformulatingPendingNootaIds.value, notification.external_id]

  try {
    const response = await fetch(`${apiBaseUrl}/integrations/noota/google-drive/rewrite-report`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        site_id: config.siteId,
        external_id: notification.external_id,
        formatted_report: notification.formatted_report
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
      throw new Error(detail || 'Impossible de reformuler le compte rendu.')
    }

    const rewritten = (await response.json()) as RewriteReportResponse
    updatePendingNootaReport(notification.external_id, rewritten.formatted_report)
  } catch (error) {
    messages.value.push(createMessage('agent', buildErrorMessage(error)))
    syncActiveConversation()
  } finally {
    reformulatingPendingNootaIds.value = reformulatingPendingNootaIds.value.filter((item) => item !== notification.external_id)
  }
}

async function syncPendingNootaReports() {
  if (!config.siteId) return

  try {
    const response = await fetch(
      `${apiBaseUrl}/integrations/noota/google-drive/pending?site_id=${encodeURIComponent(config.siteId)}&limit=20`
    )
    if (!response.ok) return

    const payload = (await response.json()) as { items?: NootaPendingNotification[] }
    const hiddenIds = new Set(hiddenPendingNootaIds.value)
    const items = payload.items ?? []

    for (const item of items) {
      knownPendingNootaIds.add(item.external_id)
    }

    pendingNootaReports.value = items.map((item) => ({
      ...item,
      suggested_appointments: Array.isArray(item.suggested_appointments) ? item.suggested_appointments : [],
      suggested_tasks: Array.isArray(item.suggested_tasks) ? item.suggested_tasks : []
    }))
    pendingNootaToasts.value = pendingNootaReports.value.filter((item) => !hiddenIds.has(item.external_id))
    persistPendingNootaToasts()
  } catch {
    // Keep the application usable if Drive polling fails.
  }
}

async function fetchPendingNootaReport(externalId: string): Promise<NootaPendingNotification> {
  const response = await fetch(
    `${apiBaseUrl}/integrations/noota/google-drive/pending/${encodeURIComponent(externalId)}?site_id=${encodeURIComponent(config.siteId)}`
  )
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error("Endpoint de validation introuvable côté API. Redemarrez le backend pour charger la nouvelle route.")
    }

    let detail = ''
  try {
      const payload = await response.json()
      if (typeof payload?.detail === 'string' && payload.detail.trim()) {
        detail = payload.detail.trim()
      }
    } catch {
      detail = ''
    }
    throw new Error(detail || `Rapport Drive indisponible (${response.status}).`)
  }

  const item = (await response.json()) as NootaPendingNotification
  const normalizedItem = {
    ...item,
    suggested_appointments: Array.isArray(item.suggested_appointments) ? item.suggested_appointments : [],
    suggested_tasks: Array.isArray(item.suggested_tasks) ? item.suggested_tasks : []
  }
  const upsert = (items: NootaPendingNotification[]) => [
    normalizedItem,
    ...items.filter((existing) => existing.external_id !== normalizedItem.external_id)
  ]

  pendingNootaReports.value = upsert(pendingNootaReports.value)
  if (!hiddenPendingNootaIds.value.includes(normalizedItem.external_id)) {
    pendingNootaToasts.value = upsert(pendingNootaToasts.value)
  }
  knownPendingNootaIds.add(normalizedItem.external_id)
  persistPendingNootaToasts()
  return normalizedItem
}

async function syncDriveStatus() {
  if (!config.siteId) return

  driveStatusLoading.value = true
  driveStatusError.value = ''

  try {
    const response = await fetch(`${apiBaseUrl}/integrations/noota/google-drive/status?site_id=${encodeURIComponent(config.siteId)}&limit=20`)
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
      const selectedTaskCount = selectedPendingNootaTaskKeys.value.length
      markPendingNootaAsHidden(notification.external_id)
      pendingNootaToasts.value = pendingNootaToasts.value.filter((item) => item.external_id !== notification.external_id)
      pendingNootaReports.value = pendingNootaReports.value.filter((item) => item.external_id !== notification.external_id)
      persistPendingNootaToasts()
      closePendingNootaPreview()
      messages.value.push(
        createMessage(
          'agent',
          `Maquette validee : le compte rendu "${notification.meeting_title}" serait remis en forme, ajoute a la base puis envoye a ${pendingNootaRecipientEmail.value.trim()}. ${selectedTaskCount} tache(s) selectionnee(s) seraient ajoutees au dossier client.`
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
        recipient_email: pendingNootaRecipientEmail.value.trim(),
        formatted_report: notification.formatted_report,
        client_name: pendingNootaClientName.value.trim(),
        selected_task_keys: selectedPendingNootaTaskKeys.value
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
    const selectedTaskCount = selectedPendingNootaTaskKeys.value.length
    markPendingNootaAsHidden(notification.external_id)
    pendingNootaToasts.value = pendingNootaToasts.value.filter((item) => item.external_id !== notification.external_id)
    pendingNootaReports.value = pendingNootaReports.value.filter((item) => item.external_id !== notification.external_id)
    persistPendingNootaToasts()
    closePendingNootaPreview()

    for (const appointment of imported.scheduled_appointments ?? []) {
      pushAppointmentToast({
        id: appointment.notification_id || appointment.event_id,
        site_id: config.siteId,
        client_name: pendingNootaClientName.value.trim() || notification.client_name,
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
          ? `Compte rendu importe, remis en forme et envoye par mail : ${notification.meeting_title}. ${scheduledCount} rendez-vous ont aussi ete ajoutes a l'agenda. ${selectedTaskCount} tache(s) selectionnee(s) ont ete ajoutees au dossier client.`
          : `Compte rendu importe, remis en forme et envoye par mail : ${notification.meeting_title}. ${selectedTaskCount} tache(s) selectionnee(s) ont ete ajoutees au dossier client.`
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

async function sendOfferProjectMessage(prefilledMessage?: string) {
  const message = prepareOutgoingMessage(prefilledMessage ?? offerProjectDraft.value)
  if (!message || isOfferProjectLoading.value) return

  offerProjectDraft.value = ''
  isOfferProjectLoading.value = true

  try {
    const response = await fetch(`${apiBaseUrl}/offers/projects/${activeOfferProjectId.value}/messages?site_id=${encodeURIComponent(config.siteId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content: message
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

    const data = (await response.json()) as OfferAssistantResponse
    await refreshOfferProjectContext(data.project.id)
  } catch (error) {
    offerProjectMessages.value.push(createMessage('agent', buildErrorMessage(error)))
  } finally {
    isOfferProjectLoading.value = false
  }
}

function setOfferTaskChoiceDecision(taskKey: string, decision: OfferTaskChoiceDecision) {
  offerTaskChoices.value = offerTaskChoices.value.map((item) => (
    item.task_key === taskKey ? { ...item, decision } : item
  ))
}

async function submitOfferTaskChoices() {
  if (!offerTaskChoices.value.length || isOfferTaskChoicesSaving.value || isOfferProjectLoading.value) return

  const groups: Record<Exclude<OfferTaskChoiceDecision, 'pending'>, string[]> = {
    include: [],
    later: [],
    forgotten: []
  }
  offerTaskChoices.value.forEach((item, index) => {
    if (item.decision === 'include' || item.decision === 'later' || item.decision === 'forgotten') {
      groups[item.decision].push(`T${index + 1}`)
    }
  })

  const parts = [
    groups.include.length ? `dans l'offre ${groups.include.join(' ')}` : '',
    groups.later.length ? `plus tard ${groups.later.join(' ')}` : '',
    groups.forgotten.length ? `oublier ${groups.forgotten.join(' ')}` : ''
  ].filter(Boolean)

  if (!parts.length) return

  isOfferTaskChoicesSaving.value = true
  try {
    await sendOfferProjectMessage(parts.join(', '))
  } finally {
    isOfferTaskChoicesSaving.value = false
  }
}

async function addOfferProjectEmail() {
  if (!activeOfferProjectId.value || !offerProjectEmailDraft.value.trim() || isOfferProjectEmailSubmitting.value) return
  isOfferProjectEmailSubmitting.value = true
  try {
    const response = await fetch(`${apiBaseUrl}/offers/projects/${activeOfferProjectId.value}/emails`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subject: offerProjectEmailSubject.value,
        sender: offerProjectEmailSender.value,
        content: offerProjectEmailDraft.value
      })
    })
    if (!response.ok) {
      throw new Error("Impossible d'ajouter l'email au projet.")
    }
    offerProjectEmailDraft.value = ''
    offerProjectEmailSubject.value = ''
    offerProjectEmailSender.value = ''
    await refreshOfferProjectContext(activeOfferProjectId.value)
  } finally {
    isOfferProjectEmailSubmitting.value = false
  }
}

async function uploadOfferProjectFiles() {
  if (!activeOfferProjectId.value || !offerProjectSelectedFiles.value.length || isOfferProjectUploadingFiles.value) return
  isOfferProjectUploadingFiles.value = true
  try {
    for (const file of offerProjectSelectedFiles.value) {
      const formData = new FormData()
      formData.append('file', file)
      const response = await fetch(`${apiBaseUrl}/offers/projects/${activeOfferProjectId.value}/files`, {
        method: 'POST',
        body: formData
      })
      if (!response.ok) {
        throw new Error(`Impossible d'ajouter le fichier ${file.name}.`)
      }
    }
    offerProjectSelectedFiles.value = []
    await refreshOfferProjectContext(activeOfferProjectId.value)
  } finally {
    isOfferProjectUploadingFiles.value = false
  }
}

async function generateOfferProject() {
  if (!activeOfferProjectId.value || isOfferProjectGenerating.value) return
  isOfferProjectGenerating.value = true
  try {
    const response = await fetch(
      `${apiBaseUrl}/offers/projects/${activeOfferProjectId.value}/generate?site_id=${encodeURIComponent(config.siteId)}`,
      { method: 'POST' }
    )
    if (!response.ok) {
      let detail = ''
      try {
        const payload = await response.json()
        detail = typeof payload?.detail === 'string' ? payload.detail : ''
      } catch {
        detail = ''
      }
      throw new Error(detail || "Impossible de generer l'offre.")
    }
    applyOfferProjectContext((await response.json()) as OfferProjectContext)
  } finally {
    isOfferProjectGenerating.value = false
  }
}

async function createOfferProjectExport(exportFormat: 'docx' | 'pdf') {
  if (!activeOfferProjectId.value) return
  const response = await fetch(`${apiBaseUrl}/offers/projects/${activeOfferProjectId.value}/exports/${exportFormat}`, {
    method: 'POST'
  })
  if (!response.ok) {
    let detail = ''
    try {
      const payload = await response.json()
      detail = typeof payload?.detail === 'string' ? payload.detail : ''
    } catch {
      detail = ''
    }
    throw new Error(detail || `Impossible de generer le fichier ${exportFormat.toUpperCase()}.`)
  }
  const created = (await response.json()) as OfferProjectExportSummary
  offerProjectExports.value = [created, ...offerProjectExports.value.filter((item) => item.id !== created.id)]
  window.location.href = `${apiBaseUrl}/offers/projects/${activeOfferProjectId.value}/exports/${created.id}/download`
}

async function refreshDriveMonitoring() {
  await Promise.all([syncDriveStatus(), syncPendingNootaReports()])
}

async function startPolling() {
  if (pollingStarted) return
  pollingStarted = true

  loadConversations()
  try {
    await loadClients()
    await loadOfferProjects()
  } catch {
    // Keep the application usable if offer project loading fails.
  }
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
  clients,
  clientTasks,
  clientTasksLoading,
  clientsLoading,
  clientsError,
  appointmentToasts,
  pendingNootaToasts,
  pendingNootaReports,
  selectedPendingNoota,
  pendingNootaRecipientEmail,
  pendingNootaClientName,
  selectedPendingNootaTaskKeys,
  schedulingSuggestionKeys,
  scheduledSuggestionKeys,
  suggestionErrors,
  driveStatus,
  driveStatusLoading,
  driveStatusError,
  conversations,
  activeConversationId,
  offerProjects,
  activeOfferProjectId,
  offerProjectMessages,
  offerProjectDraft,
  isOfferProjectLoading,
  offerProjectMissingItems,
  offerProjectEmails,
  offerProjectFiles,
  offerProjectReferences,
  offerProjectTeamProfiles,
  offerProjectExports,
  offerLinkedClient,
  offerLinkedClientProject,
  offerClientArtifacts,
  offerClientRecentEvents,
  offerClientProjectTasks,
  offerTaskChoices,
  generatedOfferMarkdown,
  offerProjectTitle,
  offerProjectClientName,
  offerProjectSector,
  offerProjectRequestSummary,
  offerProjectScopeDetails,
  offerProjectDeliverables,
  offerProjectPlanningDetails,
  offerProjectPricingDetails,
  offerProjectTimeSpentDetails,
  offerProjectTeamDetails,
  offerProjectConstraints,
  offerProjectEmailDraft,
  offerProjectEmailSubject,
  offerProjectEmailSender,
  offerProjectSelectedFiles,
  isOfferProjectGenerating,
  isOfferProjectEmailSubmitting,
  isOfferProjectSavingConfig,
  isOfferProjectUploadingFiles,
  isOfferTaskChoicesSaving,
  importingPendingNootaIds,
  reformulatingPendingNootaIds,
  canSend,
  activeConversation,
  activeConversationTitle,
  activeOfferProject,
  activeOfferProjectTitle,
  activeOfferProjectCompletionRatio,
  canSendOfferProjectMessage,
  hasSelectedSources,
  loadClients,
  loadClientTasks,
  suggestClientTasks,
  updateClientTaskStatus,
  createClient,
  updateClient,
  deleteClient,
  startNewConversation,
  openConversation,
  deleteConversation,
  renameConversation,
  startNewOfferProject,
  openOfferProject,
  deleteOfferProject,
  renameOfferProject,
  saveOfferProjectConfig,
  setOfferProjectSelectedFiles,
  openSourcesForMessage,
  dismissToast,
  suggestionKey,
  taskSuggestionKey,
  openPendingNootaPreview,
  closePendingNootaPreview,
  togglePendingNootaTask,
  dismissPendingNootaToast,
  updatePendingNootaClientName,
  reformulatePendingNootaReport,
  schedulePendingNootaSuggestion,
  fetchPendingNootaReport,
  importPendingNootaReport,
  sendMessage,
  sendOfferProjectMessage,
  setOfferTaskChoiceDecision,
  submitOfferTaskChoices,
  addOfferProjectEmail,
  uploadOfferProjectFiles,
  generateOfferProject,
  createOfferProjectExport,
  refreshOfferProjectContext,
  syncDriveStatus,
  syncPendingNootaReports,
  refreshDriveMonitoring,
  startPolling,
  stopPolling
}

export function useAgentiaState() {
  return agentiaState
}
