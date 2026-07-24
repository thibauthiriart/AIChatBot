<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { formatConversationDate, useAgentiaState } from '../composables/useAgentiaState'

const state = useAgentiaState()
const messagesContainer = ref<HTMLElement | null>(null)
const editingProjectId = ref('')
const editingTitle = ref('')

function onTextareaKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey) return
  event.preventDefault()
  void state.sendOfferProjectMessage()
}

function startTitleEdit(id: string, title: string) {
  editingProjectId.value = id
  editingTitle.value = title
}

function saveTitleEdit(id: string) {
  state.renameOfferProject(id, editingTitle.value)
  editingProjectId.value = ''
  editingTitle.value = ''
}

function cancelTitleEdit() {
  editingProjectId.value = ''
  editingTitle.value = ''
}

function onFilesChange(event: Event) {
  const target = event.target as HTMLInputElement | null
  state.setOfferProjectSelectedFiles(target?.files ?? null)
}

watch(
  () => state.offerProjectMessages.value.length,
  async () => {
    await nextTick()
    messagesContainer.value?.scrollTo({
      top: messagesContainer.value.scrollHeight,
      behavior: 'smooth'
    })
  },
  { immediate: true }
)

onMounted(async () => {
  await nextTick()
  messagesContainer.value?.scrollTo({ top: messagesContainer.value.scrollHeight })
})
</script>

<template>
  <section class="offer-workspace">
    <aside class="offer-projects-panel">
      <div class="offer-projects-panel__header">
        <div>
          <p class="section-eyebrow">Offres</p>
          <h2>Projets</h2>
        </div>
        <button type="button" class="history-panel__new" aria-label="Nouveau projet" @click="state.startNewOfferProject()">+</button>
      </div>

      <div class="offer-projects-panel__list">
        <article
          v-for="project in state.offerProjects.value"
          :key="project.id"
          class="history-item"
          :class="{ 'history-item--active': project.id === state.activeOfferProjectId.value }"
        >
          <div v-if="editingProjectId === project.id" class="history-item__editor">
            <input
              v-model="editingTitle"
              class="history-item__input"
              type="text"
              maxlength="80"
              @keydown.enter.prevent="saveTitleEdit(project.id)"
              @keydown.esc.prevent="cancelTitleEdit"
            />
            <div class="history-item__actions">
              <button type="button" class="history-item__link" @click="saveTitleEdit(project.id)">OK</button>
              <button type="button" class="history-item__danger" @click="cancelTitleEdit()">Annuler</button>
            </div>
          </div>

          <template v-else>
            <button type="button" class="history-item__open" @click="void state.openOfferProject(project.id)">
              <strong>{{ project.title }}</strong>
              <span>{{ formatConversationDate(project.updated_at) }} - {{ project.completion_ratio }}%</span>
            </button>
            <div class="history-item__actions">
              <button
                type="button"
                class="history-item__link"
                aria-label="Renommer le projet"
                @click="startTitleEdit(project.id, project.title)"
              >
                Renommer
              </button>
              <button
                type="button"
                class="history-item__danger"
                aria-label="Supprimer le projet"
                @click="void state.deleteOfferProject(project.id)"
              >
                Supprimer
              </button>
            </div>
          </template>
        </article>
      </div>
    </aside>

    <div class="offer-main-grid offer-main-grid--focused">
      <section class="chat-panel offer-chat-panel offer-chat-panel--primary">
        <header class="chat-panel__header offer-chat-panel__header">
          <div>
            <p class="section-eyebrow">Assistant IA</p>
            <h1>{{ state.activeOfferProjectTitle.value }}</h1>
          </div>
          <div class="offer-chat-panel__chips" aria-label="Resume du projet">
            <span>{{ state.offerProjectClientName.value || 'Client a definir' }}</span>
            <span>{{ state.activeOfferProjectCompletionRatio.value }}%</span>
            <span>{{ state.offerProjectFiles.value.length }} fichier(s)</span>
          </div>
        </header>

        <div ref="messagesContainer" class="chat-panel__messages" aria-live="polite">
          <article
            v-for="(message, index) in state.offerProjectMessages.value"
            :key="index"
            class="chat-message"
            :class="`chat-message--${message.role}`"
          >
            <div v-if="message.role === 'agent'" class="chat-message__avatar">IA</div>

            <div class="chat-message__content">
              <div class="chat-message__meta">
                <span>{{ message.role === 'agent' ? state.config.title : 'Vous' }}</span>
                <time>{{ message.createdAt }}</time>
              </div>

              <div class="chat-message__bubble">
                <p>{{ message.content }}</p>
              </div>
            </div>
          </article>

          <article v-if="state.isOfferProjectLoading.value" class="chat-message chat-message--agent">
            <div class="chat-message__avatar">IA</div>
            <div class="chat-message__content">
              <div class="chat-message__meta">
                <span>{{ state.config.title }}</span>
                <time>...</time>
              </div>
              <div class="chat-message__bubble chat-message__bubble--typing">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>
          </article>
        </div>

        <form class="chat-panel__composer" @submit.prevent="state.sendOfferProjectMessage()">
          <label class="sr-only" for="offer-project-message">Message</label>
          <div class="chat-panel__composer-box">
            <textarea
              id="offer-project-message"
              v-model="state.offerProjectDraft.value"
              rows="3"
              maxlength="1200"
              placeholder="Demandez a l'IA de cadrer l'offre, completer les zones manquantes ou generer une version."
              @keydown="onTextareaKeydown"
            />
            <div class="chat-panel__composer-actions">
              <span>{{ state.offerProjectDraft.value.length }}/1200</span>
              <button type="submit" :disabled="!state.canSendOfferProjectMessage.value">Envoyer</button>
            </div>
          </div>
        </form>
      </section>

      <aside class="offer-context-rail">
        <section class="offer-action-card">
          <div>
            <p class="section-eyebrow">Document</p>
            <h3>Brouillon</h3>
          </div>
          <button class="primary-button" type="button" :disabled="state.isOfferProjectGenerating.value" @click="void state.generateOfferProject()">
            {{ state.isOfferProjectGenerating.value ? 'Generation...' : 'Generer' }}
          </button>
          <div class="offer-export-actions">
            <button class="secondary-button" type="button" @click="void state.createOfferProjectExport('docx')">DOCX</button>
            <button class="secondary-button" type="button" @click="void state.createOfferProjectExport('pdf')">PDF</button>
          </div>
        </section>

        <details class="offer-detail-panel" open>
          <summary>
            <span>Projet</span>
            <b>{{ state.activeOfferProjectCompletionRatio.value }}%</b>
          </summary>
          <div class="offer-detail-panel__body">
            <input v-model="state.offerProjectTitle.value" class="history-item__input" type="text" placeholder="Nom du projet" />
            <input v-model="state.offerProjectClientName.value" class="history-item__input" type="text" placeholder="Nom du client" />
            <input v-model="state.offerProjectSector.value" class="history-item__input" type="text" placeholder="Secteur" />
            <textarea v-model="state.offerProjectRequestSummary.value" class="offer-email-textarea" rows="3" placeholder="Resume du besoin" />
            <textarea v-model="state.offerProjectScopeDetails.value" class="offer-email-textarea" rows="3" placeholder="Perimetre" />
            <textarea v-model="state.offerProjectDeliverables.value" class="offer-email-textarea" rows="3" placeholder="Livrables" />
            <button class="primary-button" type="button" :disabled="state.isOfferProjectSavingConfig.value" @click="void state.saveOfferProjectConfig()">
              Enregistrer
            </button>
          </div>
        </details>

        <details class="offer-detail-panel">
          <summary>
            <span>Fichiers</span>
            <b>{{ state.offerProjectFiles.value.length }}</b>
          </summary>
          <div class="offer-detail-panel__body">
            <input class="history-item__input" type="file" multiple accept=".txt,.md,.csv,.json,.pdf" @change="onFilesChange" />
            <button
              class="primary-button"
              type="button"
              :disabled="state.isOfferProjectUploadingFiles.value || !state.offerProjectSelectedFiles.value.length"
              @click="void state.uploadOfferProjectFiles()"
            >
              Ajouter
            </button>
            <article v-for="file in state.offerProjectFiles.value" :key="file.id" class="list-card list-card--compact">
              <p class="list-card__title">{{ file.filename }}</p>
              <p class="list-card__meta">{{ file.content_type || 'type non precise' }}</p>
            </article>
          </div>
        </details>

        <details class="offer-detail-panel" open>
          <summary>
            <span>Checklist</span>
            <b>{{ state.offerProjectMissingItems.value.filter((item) => item.status === 'missing').length }}</b>
          </summary>
          <div class="offer-detail-panel__body">
            <article
              v-for="item in state.offerProjectMissingItems.value"
              :key="item.key"
              class="list-card list-card--compact"
            >
              <p class="list-card__title">{{ item.label }}</p>
              <p class="list-card__meta">{{ item.status === 'completed' ? item.answer || 'Renseigne' : item.prompt }}</p>
            </article>
          </div>
        </details>

        <details class="offer-detail-panel">
          <summary>
            <span>Cadrage</span>
            <b>5</b>
          </summary>
          <div class="offer-detail-panel__body">
            <article class="list-card list-card--compact">
              <p class="list-card__title">Planning</p>
              <p class="list-card__meta">{{ state.offerProjectPlanningDetails.value || 'Non renseigne' }}</p>
            </article>
            <article class="list-card list-card--compact">
              <p class="list-card__title">Prix</p>
              <p class="list-card__meta">{{ state.offerProjectPricingDetails.value || 'Non renseigne' }}</p>
            </article>
            <article class="list-card list-card--compact">
              <p class="list-card__title">Temps passe</p>
              <p class="list-card__meta">{{ state.offerProjectTimeSpentDetails.value || 'Non renseigne' }}</p>
            </article>
            <article class="list-card list-card--compact">
              <p class="list-card__title">Equipe</p>
              <p class="list-card__meta">{{ state.offerProjectTeamDetails.value || 'Non renseigne' }}</p>
            </article>
            <article class="list-card list-card--compact">
              <p class="list-card__title">Contraintes</p>
              <p class="list-card__meta">{{ state.offerProjectConstraints.value || 'Non renseigne' }}</p>
            </article>
          </div>
        </details>

        <details v-if="state.offerLinkedClient.value" class="offer-detail-panel" open>
          <summary>
            <span>Contexte charge</span>
            <b>{{ state.offerClientProjectTasks.value.length }}</b>
          </summary>
          <div class="offer-detail-panel__body">
            <article class="list-card list-card--compact">
              <p class="list-card__title">{{ state.offerLinkedClient.value.name }}</p>
              <p class="list-card__meta">
                {{ state.offerLinkedClientProject.value?.name || 'Tous les projets client' }}
              </p>
            </article>

            <article v-for="task in state.offerClientProjectTasks.value.slice(0, 8)" :key="task.id" class="list-card list-card--compact">
              <p class="list-card__title">{{ task.title }}</p>
              <p class="list-card__meta">
                {{ task.status }}<template v-if="task.owner"> - {{ task.owner }}</template><template v-if="task.due_date"> - {{ task.due_date }}</template>
              </p>
            </article>

            <article v-for="artifact in state.offerClientArtifacts.value.slice(0, 4)" :key="artifact.id" class="list-card list-card--compact">
              <p class="list-card__title">{{ artifact.title }}</p>
              <p class="list-card__meta">{{ artifact.excerpt || artifact.kind }}</p>
            </article>

            <article v-for="event in state.offerClientRecentEvents.value.slice(0, 4)" :key="event.id" class="list-card list-card--compact">
              <p class="list-card__title">{{ event.title }}</p>
              <p class="list-card__meta">{{ formatConversationDate(event.event_at) }} - {{ event.event_type }}</p>
            </article>
          </div>
        </details>

        <details v-if="state.offerTaskChoices.value.length" class="offer-detail-panel" open>
          <summary>
            <span>Taches offre</span>
            <b>{{ state.offerTaskChoices.value.filter((item) => item.decision !== 'pending').length }}/{{ state.offerTaskChoices.value.length }}</b>
          </summary>
          <div class="offer-detail-panel__body">
            <article
              v-for="(task, index) in state.offerTaskChoices.value"
              :key="task.task_key"
              class="offer-task-choice"
            >
              <div class="offer-task-choice__header">
                <span>T{{ index + 1 }}</span>
                <p>{{ task.title }}</p>
              </div>
              <p v-if="task.detail" class="offer-task-choice__detail">{{ task.detail }}</p>
              <div class="offer-task-choice__options" role="group" :aria-label="`Classer ${task.title}`">
                <button
                  type="button"
                  :class="{ 'offer-task-choice__option--active': task.decision === 'include' }"
                  @click="state.setOfferTaskChoiceDecision(task.task_key, 'include')"
                >
                  Offre
                </button>
                <button
                  type="button"
                  :class="{ 'offer-task-choice__option--active': task.decision === 'later' }"
                  @click="state.setOfferTaskChoiceDecision(task.task_key, 'later')"
                >
                  Plus tard
                </button>
                <button
                  type="button"
                  :class="{ 'offer-task-choice__option--active': task.decision === 'forgotten' }"
                  @click="state.setOfferTaskChoiceDecision(task.task_key, 'forgotten')"
                >
                  Oublie
                </button>
              </div>
            </article>

            <button
              class="primary-button"
              type="button"
              :disabled="state.isOfferTaskChoicesSaving.value || state.isOfferProjectLoading.value"
              @click="void state.submitOfferTaskChoices()"
            >
              {{ state.isOfferTaskChoicesSaving.value ? 'Enregistrement...' : 'Enregistrer les choix' }}
            </button>
          </div>
        </details>

        <details class="offer-detail-panel">
          <summary>
            <span>Emails et references</span>
            <b>{{ state.offerProjectEmails.value.length + state.offerProjectReferences.value.length }}</b>
          </summary>
          <div class="offer-detail-panel__body">
            <input v-model="state.offerProjectEmailSubject.value" class="history-item__input" type="text" placeholder="Objet de l'email" />
            <input v-model="state.offerProjectEmailSender.value" class="history-item__input" type="text" placeholder="Expediteur" />
            <textarea v-model="state.offerProjectEmailDraft.value" class="offer-email-textarea" rows="4" placeholder="Contenu utile de l'email" />
            <button class="primary-button" type="button" :disabled="state.isOfferProjectEmailSubmitting.value || !state.offerProjectEmailDraft.value.trim()" @click="void state.addOfferProjectEmail()">
              Ajouter
            </button>
            <article v-for="email in state.offerProjectEmails.value" :key="email.id" class="list-card list-card--compact">
              <p class="list-card__title">{{ email.subject || 'Email sans objet' }}</p>
              <p class="list-card__meta">{{ email.sender || 'Expediteur non precise' }}</p>
            </article>
            <article v-for="reference in state.offerProjectReferences.value" :key="reference.id" class="list-card list-card--compact">
              <p class="list-card__title">{{ reference.title }}</p>
              <p class="list-card__meta">{{ reference.client_name || 'Client non precise' }}<template v-if="reference.sector"> - {{ reference.sector }}</template></p>
            </article>
          </div>
        </details>

        <details v-if="state.generatedOfferMarkdown.value || state.offerProjectExports.value.length" class="offer-detail-panel">
          <summary>
            <span>Sorties</span>
            <b>{{ state.offerProjectExports.value.length }}</b>
          </summary>
          <div class="offer-detail-panel__body">
            <article v-for="item in state.offerProjectExports.value" :key="item.id" class="list-card list-card--compact">
              <p class="list-card__title">{{ item.filename }}</p>
              <p class="list-card__meta">{{ formatConversationDate(item.created_at) }}</p>
            </article>
            <p v-if="state.generatedOfferMarkdown.value" class="offer-markdown-preview">{{ state.generatedOfferMarkdown.value }}</p>
          </div>
        </details>
      </aside>
    </div>
  </section>
</template>
