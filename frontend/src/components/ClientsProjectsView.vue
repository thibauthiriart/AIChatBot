<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { formatConversationDate, useAgentiaState } from '../composables/useAgentiaState'
import type { ClientCreatePayload, ClientItem, ClientProjectTask, ClientProjectTaskStatus, ClientUpdatePayload } from '../types'
import type { OfferProjectSummary } from '../types'

type ClientProjectGroup = {
  id: string
  name: string
  sector: string
  status: string
  summary: string
  externalRef: string
  aliases: string[]
  source: 'database' | 'offers'
  client: ClientItem | null
  projects: OfferProjectSummary[]
  latestUpdate: string
  averageCompletion: number
}

const taskStatusLabels: Record<ClientProjectTaskStatus, string> = {
  proposed: 'A classer',
  done: 'Traite',
  later: 'Plus tard',
  abandoned: 'Abandonne'
}

const state = useAgentiaState()
const searchQuery = ref('')
const clientName = ref('')
const clientShortName = ref('')
const clientSector = ref('')
const clientStatus = ref('')
const clientAliases = ref('')
const clientSummary = ref('')
const isSubmittingClient = ref(false)
const editingClientId = ref('')
const editName = ref('')
const editShortName = ref('')
const editSector = ref('')
const editStatus = ref('')
const editAliases = ref('')
const editSummary = ref('')
const editExternalRef = ref('')
const isSavingClient = ref(false)
const clientPendingDeletion = ref<ClientProjectGroup | null>(null)
const isDeletingClient = ref(false)

function normalizeClientName(value: string): string {
  return value.trim().toLowerCase()
}

const clientGroups = computed<ClientProjectGroup[]>(() => {
  const groups = new Map<string, ClientProjectGroup>()

  for (const client of state.clients.value) {
    const name = client.name.trim()
    if (!name) continue

    groups.set(normalizeClientName(name), {
      id: client.id,
      name,
      sector: client.sector || 'Secteur a definir',
      status: client.status || 'Statut a definir',
      summary: client.summary || '',
      externalRef: client.external_ref || '',
      aliases: client.aliases ?? [],
      source: 'database',
      client,
      projects: [],
      latestUpdate: '',
      averageCompletion: 0
    })
  }

  for (const project of state.offerProjects.value) {
    const clientName = project.client_name?.trim() || 'Client a definir'
    const key = normalizeClientName(clientName)
    const existing = groups.get(key)

    if (existing) {
      existing.projects.push(project)
      if ((!existing.sector || existing.sector === 'Secteur a definir') && project.sector) {
        existing.sector = project.sector
      }
      continue
    }

    groups.set(key, {
      id: key,
      name: clientName,
      sector: project.sector || 'Secteur a definir',
      status: 'Hors BDD client',
      summary: '',
      externalRef: '',
      aliases: [],
      source: 'offers',
      client: null,
      projects: [project],
      latestUpdate: project.updated_at,
      averageCompletion: project.completion_ratio
    })
  }

  return Array.from(groups.values())
    .map((group) => {
      const projects = [...group.projects].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
      return {
        ...group,
        projects,
        latestUpdate: projects[0]?.updated_at ?? '',
        averageCompletion: projects.length
          ? Math.round(projects.reduce((total, project) => total + project.completion_ratio, 0) / projects.length)
          : 0
      }
    })
    .sort((a, b) => {
      const latestDiff = Date.parse(b.latestUpdate || '1970-01-01') - Date.parse(a.latestUpdate || '1970-01-01')
      return latestDiff || a.name.localeCompare(b.name)
    })
})

const filteredClientGroups = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return clientGroups.value

  return clientGroups.value.filter((group) => {
    return (
      group.name.toLowerCase().includes(query) ||
      group.sector.toLowerCase().includes(query) ||
      group.status.toLowerCase().includes(query) ||
      group.summary.toLowerCase().includes(query) ||
      group.externalRef.toLowerCase().includes(query) ||
      group.aliases.some((alias) => alias.toLowerCase().includes(query)) ||
      group.projects.some((project) => project.title.toLowerCase().includes(query) || project.status.toLowerCase().includes(query))
    )
  })
})

const totalProjects = computed(() => state.offerProjects.value.length)
const activeProjects = computed(() => state.offerProjects.value.filter((project) => project.status !== 'archived').length)
const databaseClientCount = computed(() => state.clients.value.length)

watch(
  () => state.clients.value.map((client) => client.id).join(','),
  () => {
    for (const client of state.clients.value) {
      if (!state.clientTasks.value[client.id] && !state.clientTasksLoading.value[client.id]) {
        void state.loadClientTasks(client.id)
      }
    }
  },
  { immediate: true }
)

function tasksForClient(client: ClientProjectGroup): ClientProjectTask[] {
  if (!client.client) return []
  return state.clientTasks.value[client.client.id] ?? []
}

function taskCountByStatus(client: ClientProjectGroup, status: ClientProjectTaskStatus): number {
  return tasksForClient(client).filter((task) => task.status === status).length
}

function isLoadingTasks(client: ClientProjectGroup): boolean {
  return Boolean(client.client && state.clientTasksLoading.value[client.client.id])
}

async function suggestTasks(client: ClientProjectGroup) {
  if (!client.client) return
  await state.suggestClientTasks(client.client.id)
}

async function classifyTask(task: ClientProjectTask, status: ClientProjectTaskStatus) {
  await state.updateClientTaskStatus(task.id, status)
}

async function submitClient() {
  const name = clientName.value.trim()
  if (!name || isSubmittingClient.value) return

  isSubmittingClient.value = true
  const payload: ClientCreatePayload = {
    name,
    short_name: clientShortName.value.trim() || null,
    aliases: clientAliases.value
      .split(',')
      .map((alias) => alias.trim())
      .filter(Boolean),
    sector: clientSector.value.trim(),
    status: clientStatus.value.trim(),
    summary: clientSummary.value.trim()
  }

  try {
    await state.createClient(payload)
    clientName.value = ''
    clientShortName.value = ''
    clientSector.value = ''
    clientStatus.value = ''
    clientAliases.value = ''
    clientSummary.value = ''
  } finally {
    isSubmittingClient.value = false
  }
}

function startClientEdit(client: ClientProjectGroup) {
  if (!client.client) return
  editingClientId.value = client.client.id
  editName.value = client.client.name
  editShortName.value = client.client.short_name || ''
  editSector.value = client.client.sector || ''
  editStatus.value = client.client.status || ''
  editAliases.value = (client.client.aliases ?? []).join(', ')
  editSummary.value = client.client.summary || ''
  editExternalRef.value = client.client.external_ref || ''
}

function cancelClientEdit() {
  editingClientId.value = ''
  editName.value = ''
  editShortName.value = ''
  editSector.value = ''
  editStatus.value = ''
  editAliases.value = ''
  editSummary.value = ''
  editExternalRef.value = ''
}

async function saveClientEdit() {
  const name = editName.value.trim()
  if (!editingClientId.value || !name || isSavingClient.value) return

  isSavingClient.value = true
  const payload: ClientUpdatePayload = {
    name,
    short_name: editShortName.value.trim() || null,
    aliases: editAliases.value
      .split(',')
      .map((alias) => alias.trim())
      .filter(Boolean),
    sector: editSector.value.trim(),
    status: editStatus.value.trim(),
    summary: editSummary.value.trim(),
    external_ref: editExternalRef.value.trim()
  }

  try {
    await state.updateClient(editingClientId.value, payload)
    cancelClientEdit()
  } catch {
    // Error details are already exposed through state.clientsError.
  } finally {
    isSavingClient.value = false
  }
}

function requestClientDeletion(client: ClientProjectGroup) {
  if (client.source !== 'database') return
  clientPendingDeletion.value = client
}

function cancelClientDeletion() {
  if (isDeletingClient.value) return
  clientPendingDeletion.value = null
}

async function confirmClientDeletion() {
  if (!clientPendingDeletion.value || isDeletingClient.value) return

  isDeletingClient.value = true
  try {
    await state.deleteClient(clientPendingDeletion.value.id)
    if (editingClientId.value === clientPendingDeletion.value.id) {
      cancelClientEdit()
    }
    clientPendingDeletion.value = null
  } catch {
    // Error details are already exposed through state.clientsError.
  } finally {
    isDeletingClient.value = false
  }
}

function openProject(projectId: string) {
  void state.openOfferProject(projectId)
  window.location.hash = '/offers'
}
</script>

<template>
  <section class="page-view clients-view">
    <div v-if="clientPendingDeletion" class="modal-backdrop" @click="cancelClientDeletion">
      <section class="confirm-modal" @click.stop>
        <div>
          <p class="section-eyebrow">Suppression</p>
          <h2>Supprimer ce client ?</h2>
          <p>
            Cette action supprimera la fiche client <strong>{{ clientPendingDeletion.name }}</strong>, ainsi que ses projets,
            documents et evenements rattaches en base.
          </p>
        </div>

        <p v-if="state.clientsError.value" class="client-create-panel__error">{{ state.clientsError.value }}</p>

        <div class="confirm-modal__actions">
          <button class="secondary-button" type="button" :disabled="isDeletingClient" @click="cancelClientDeletion">Annuler</button>
          <button class="danger-button" type="button" :disabled="isDeletingClient" @click="confirmClientDeletion">
            {{ isDeletingClient ? 'Suppression...' : 'Supprimer' }}
          </button>
        </div>
      </section>
    </div>

    <div class="page-view__hero page-view__hero--compact">
      <div>
        <p class="section-eyebrow">Clients</p>
        <h2>Clients et projets associes</h2>
        <p class="page-view__intro">
          Vue consolidee des clients detectes dans les propositions d'offres, avec leurs projets rattaches et leur avancement.
        </p>
      </div>

      <div class="metric-grid metric-grid--compact">
        <article class="metric-card">
          <span>Clients</span>
          <strong>{{ clientGroups.length }}</strong>
          <p>Comptes regroupes</p>
        </article>
        <article class="metric-card">
          <span>En BDD</span>
          <strong>{{ databaseClientCount }}</strong>
          <p>Fiches clients</p>
        </article>
        <article class="metric-card">
          <span>Projets</span>
          <strong>{{ totalProjects }}</strong>
          <p>{{ activeProjects }} actif(s)</p>
        </article>
      </div>
    </div>

    <div class="clients-admin-grid">
      <form class="client-create-panel" @submit.prevent="submitClient">
        <div>
          <p class="section-eyebrow">Base clients</p>
          <h3>Ajouter un client</h3>
        </div>

        <div class="client-create-panel__grid">
          <input v-model="clientName" class="history-item__input" type="text" maxlength="160" required placeholder="Nom du client" />
          <input v-model="clientShortName" class="history-item__input" type="text" maxlength="80" placeholder="Nom court" />
          <input v-model="clientSector" class="history-item__input" type="text" maxlength="120" placeholder="Secteur" />
          <input v-model="clientStatus" class="history-item__input" type="text" maxlength="80" placeholder="Statut" />
        </div>

        <input v-model="clientAliases" class="history-item__input" type="text" placeholder="Alias separes par des virgules" />
        <textarea v-model="clientSummary" class="offer-email-textarea" rows="3" maxlength="4000" placeholder="Resume client" />

        <div class="client-create-panel__actions">
          <button class="primary-button" type="submit" :disabled="isSubmittingClient || !clientName.trim()">
            Ajouter en BDD
          </button>
          <span v-if="state.clientsLoading.value">Chargement des clients...</span>
          <span v-else-if="state.clientsError.value" class="client-create-panel__error">{{ state.clientsError.value }}</span>
        </div>
      </form>

      <div class="clients-toolbar">
        <label class="sr-only" for="client-search">Rechercher</label>
        <input
          id="client-search"
          v-model="searchQuery"
          class="history-item__input"
          type="search"
          placeholder="Rechercher un client, secteur, projet ou statut"
        />
      </div>
    </div>

    <div v-if="filteredClientGroups.length" class="clients-list">
      <article v-for="client in filteredClientGroups" :key="client.id" class="client-project-card">
        <template v-if="editingClientId === client.id">
          <form class="client-edit-form" @submit.prevent="saveClientEdit">
            <div class="client-create-panel__grid">
              <input v-model="editName" class="history-item__input" type="text" maxlength="160" required placeholder="Nom du client" />
              <input v-model="editShortName" class="history-item__input" type="text" maxlength="80" placeholder="Nom court" />
              <input v-model="editSector" class="history-item__input" type="text" maxlength="120" placeholder="Secteur" />
              <input v-model="editStatus" class="history-item__input" type="text" maxlength="80" placeholder="Statut" />
            </div>

            <input v-model="editAliases" class="history-item__input" type="text" placeholder="Alias separes par des virgules" />
            <input v-model="editExternalRef" class="history-item__input" type="text" maxlength="120" placeholder="Reference externe" />
            <textarea v-model="editSummary" class="offer-email-textarea" rows="4" maxlength="4000" placeholder="Resume client" />

            <div class="client-create-panel__actions">
              <button class="primary-button" type="submit" :disabled="isSavingClient || !editName.trim()">Enregistrer</button>
              <button class="secondary-button" type="button" :disabled="isSavingClient" @click="cancelClientEdit">Annuler</button>
              <span v-if="state.clientsError.value" class="client-create-panel__error">{{ state.clientsError.value }}</span>
            </div>
          </form>
        </template>

        <template v-else>
          <header class="client-project-card__header">
            <div>
              <h3>{{ client.name }}</h3>
              <p>{{ client.sector }}</p>
            </div>
            <div class="client-project-card__stats">
              <span>{{ client.source === 'database' ? 'BDD' : 'Projet seul' }}</span>
              <span>{{ client.status }}</span>
              <span>{{ client.projects.length }} projet(s)</span>
              <span>{{ client.averageCompletion }}% moyen</span>
            </div>
          </header>

          <div v-if="client.source === 'database'" class="client-project-card__actions">
            <button type="button" class="history-item__link" @click="startClientEdit(client)">Modifier</button>
            <button type="button" class="history-item__link" :disabled="isLoadingTasks(client)" @click="suggestTasks(client)">
              {{ isLoadingTasks(client) ? 'Analyse...' : 'Extraire les taches' }}
            </button>
            <button type="button" class="history-item__danger" @click="requestClientDeletion(client)">Supprimer</button>
          </div>

          <div v-if="client.aliases.length || client.externalRef" class="client-project-card__details">
            <span v-if="client.aliases.length">Alias: {{ client.aliases.join(', ') }}</span>
            <span v-if="client.externalRef">Ref: {{ client.externalRef }}</span>
          </div>

          <p v-if="client.summary" class="client-project-card__summary">{{ client.summary }}</p>

          <div v-if="client.projects.length" class="client-project-card__projects">
            <button
              v-for="project in client.projects"
              :key="project.id"
              type="button"
              class="client-project-row"
              @click="openProject(project.id)"
            >
              <span>
                <strong>{{ project.title }}</strong>
                <small>Mis a jour le {{ formatConversationDate(project.updated_at) }}</small>
              </span>
              <span class="client-project-row__meta">
                <em>{{ project.status || 'statut non precise' }}</em>
                <b>{{ project.completion_ratio }}%</b>
              </span>
            </button>
          </div>

          <p v-else class="empty-state">Aucun projet d'offre associe pour le moment.</p>

          <section v-if="client.source === 'database'" class="client-task-panel">
            <header class="client-task-panel__header">
              <div>
                <h4>Taches issues des reunions</h4>
                <p>{{ taskCountByStatus(client, 'proposed') }} a classer, {{ taskCountByStatus(client, 'later') }} plus tard</p>
              </div>
              <span>{{ tasksForClient(client).length }} tache(s)</span>
            </header>

            <div v-if="tasksForClient(client).length" class="client-task-list">
              <article v-for="task in tasksForClient(client)" :key="task.id" class="client-task-item">
                <div>
                  <strong>{{ task.title }}</strong>
                  <small>
                    {{ taskStatusLabels[task.status] }}
                    <template v-if="task.project_name"> - {{ task.project_name }}</template>
                    <template v-if="task.owner"> - {{ task.owner }}</template>
                    <template v-if="task.due_date"> - {{ task.due_date }}</template>
                  </small>
                </div>

                <div class="client-task-item__actions" aria-label="Classer la tache">
                  <button type="button" :class="{ 'client-task-item__button--active': task.status === 'done' }" @click="classifyTask(task, 'done')">
                    Traite
                  </button>
                  <button type="button" :class="{ 'client-task-item__button--active': task.status === 'later' }" @click="classifyTask(task, 'later')">
                    Plus tard
                  </button>
                  <button
                    type="button"
                    :class="{ 'client-task-item__button--active': task.status === 'abandoned' }"
                    @click="classifyTask(task, 'abandoned')"
                  >
                    Abandonner
                  </button>
                </div>
              </article>
            </div>

            <p v-else class="empty-state">
              Aucune tache detectee. Lancez l'extraction apres import des comptes rendus.
            </p>
          </section>
        </template>
      </article>
    </div>

    <p v-else class="empty-state">
      Aucun client trouve. Creez ou completez un projet d'offre pour alimenter cette liste.
    </p>
  </section>
</template>
