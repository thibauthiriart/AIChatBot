<script setup lang="ts">
import { ref, watch } from 'vue'
import { formatConversationDate, formatDateTimeWithTimezone, useAgentiaState } from '../composables/useAgentiaState'

const state = useAgentiaState()
const showValidationConfirmation = ref(false)

function closePreview() {
  showValidationConfirmation.value = false
  state.closePendingNootaPreview()
}

function requestValidationConfirmation() {
  if (!state.selectedPendingNoota.value) return
  showValidationConfirmation.value = true
}

async function confirmValidation() {
  if (!state.selectedPendingNoota.value) return
  showValidationConfirmation.value = false
  await state.importPendingNootaReport(state.selectedPendingNoota.value)
}

watch(
  () => state.selectedPendingNoota.value?.external_id,
  () => {
    showValidationConfirmation.value = false
  }
)
</script>

<template>
  <div
    v-if="state.selectedPendingNoota.value"
    class="modal-backdrop"
    @click="closePreview()"
  >
    <section class="modal-card" @click.stop>
      <div class="modal-card__header">
        <div>
          <p class="section-eyebrow">Validation</p>
          <h2>{{ state.selectedPendingNoota.value.meeting_title }}</h2>
        </div>
        <button type="button" class="modal-card__close" @click="closePreview()">Fermer</button>
      </div>

      <div class="modal-card__meta">
        <span>{{ state.selectedPendingNoota.value.client_name }}</span>
        <span v-if="state.selectedPendingNoota.value.project_name">{{ state.selectedPendingNoota.value.project_name }}</span>
        <span v-if="state.selectedPendingNoota.value.meeting_at">
          {{ formatConversationDate(state.selectedPendingNoota.value.meeting_at) }}
        </span>
      </div>

      <div class="modal-card__client-box">
        <label class="modal-card__field">
          <span>Client</span>
          <input
            :value="state.pendingNootaClientName.value"
            class="modal-card__input"
            type="text"
            placeholder="Nom du client"
            @input="
              state.updatePendingNootaClientName(
                state.selectedPendingNoota.value.external_id,
                ($event.target as HTMLInputElement).value
              )
            "
          />
        </label>
      </div>

      <div v-if="state.selectedPendingNoota.value.suggested_appointments?.length" class="modal-card__suggestions">
        <div class="modal-card__suggestions-header">
          <div>
            <p class="section-eyebrow">Agenda</p>
            <h3>Rendez-vous detectes</h3>
          </div>
          <span>L'IA vous propose de les ajouter directement a l'agenda.</span>
        </div>

        <div class="modal-card__suggestions-list">
          <article
            v-for="suggestion in state.selectedPendingNoota.value.suggested_appointments"
            :key="state.suggestionKey(state.selectedPendingNoota.value.external_id, suggestion)"
            class="modal-card__suggestion"
          >
            <div>
              <strong>{{ suggestion.title }}</strong>
              <span>{{ formatDateTimeWithTimezone(suggestion.start, suggestion.timezone) }} · {{ suggestion.timezone }}</span>
              <p v-if="suggestion.source_excerpt">{{ suggestion.source_excerpt }}</p>
              <p
                v-if="state.suggestionErrors.value[state.suggestionKey(state.selectedPendingNoota.value.external_id, suggestion)]"
                class="modal-card__error"
              >
                {{ state.suggestionErrors.value[state.suggestionKey(state.selectedPendingNoota.value.external_id, suggestion)] }}
              </p>
            </div>

            <span
              v-if="state.suggestionErrors.value[state.suggestionKey(state.selectedPendingNoota.value.external_id, suggestion)]"
              class="modal-card__status modal-card__status--error"
            >
              Occupe
            </span>

            <button
              v-else
              type="button"
              class="modal-card__secondary"
              :disabled="
                state.schedulingSuggestionKeys.value.includes(
                  state.suggestionKey(state.selectedPendingNoota.value.external_id, suggestion)
                ) ||
                state.scheduledSuggestionKeys.value.includes(
                  state.suggestionKey(state.selectedPendingNoota.value.external_id, suggestion)
                )
              "
              @click="state.schedulePendingNootaSuggestion(state.selectedPendingNoota.value, suggestion)"
            >
              {{
                state.scheduledSuggestionKeys.value.includes(
                  state.suggestionKey(state.selectedPendingNoota.value.external_id, suggestion)
                )
                  ? 'Ajoute'
                  : 'Ajouter a l agenda'
              }}
            </button>
          </article>
        </div>
      </div>

      <div class="modal-card__actions">
        <button
          type="button"
          class="modal-card__secondary modal-card__secondary--reformulate"
          :disabled="
            state.reformulatingPendingNootaIds.value.includes(state.selectedPendingNoota.value.external_id) ||
            state.importingPendingNootaIds.value.includes(state.selectedPendingNoota.value.external_id)
          "
          @click="state.reformulatePendingNootaReport(state.selectedPendingNoota.value)"
        >
          {{
            state.reformulatingPendingNootaIds.value.includes(state.selectedPendingNoota.value.external_id)
              ? 'Reformulation...'
              : 'Reformuler le compte rendu'
          }}
        </button>
        <span
          v-if="state.reformulatingPendingNootaIds.value.includes(state.selectedPendingNoota.value.external_id)"
          class="modal-card__loading"
        >
          Reformulation en cours...
        </span>
      </div>

      <div v-if="state.selectedPendingNoota.value.suggested_tasks?.length" class="modal-card__suggestions">
        <div class="modal-card__suggestions-header">
          <div>
            <p class="section-eyebrow">Taches</p>
            <h3>Taches detectees</h3>
          </div>
          <span>Choisissez celles a ajouter au dossier client apres validation.</span>
        </div>

        <div class="modal-card__suggestions-list">
          <article
            v-for="task in state.selectedPendingNoota.value.suggested_tasks"
            :key="`${task.title}:${task.owner || ''}:${task.due_date || ''}`"
            class="modal-card__suggestion"
          >
            <input
              type="checkbox"
              :checked="state.selectedPendingNootaTaskKeys.value.includes(state.taskSuggestionKey(task))"
              :aria-label="`Conserver la tache ${task.title}`"
              @change="state.togglePendingNootaTask(task)"
            />
            <div>
              <strong>{{ task.title }}</strong>
              <span v-if="task.owner || task.due_date">
                <template v-if="task.owner">Responsable: {{ task.owner }}</template>
                <template v-if="task.owner && task.due_date"> · </template>
                <template v-if="task.due_date">Echeance: {{ task.due_date }}</template>
              </span>
              <p v-if="task.source_excerpt">{{ task.source_excerpt }}</p>
            </div>
          </article>
        </div>
      </div>

      <p v-else class="modal-card__empty">Aucune tache detectee dans ce compte rendu.</p>

      <pre class="modal-card__preview">{{ state.selectedPendingNoota.value.formatted_report }}</pre>

      <div class="modal-card__footer">
        <input
          v-model="state.pendingNootaRecipientEmail.value"
          class="modal-card__input"
          type="email"
          placeholder="Email destinataire"
        />
        <button
          type="button"
          class="modal-card__primary"
          :disabled="
            !state.pendingNootaClientName.value.trim() ||
            !state.pendingNootaRecipientEmail.value.trim() ||
            state.importingPendingNootaIds.value.includes(state.selectedPendingNoota.value.external_id) ||
            state.reformulatingPendingNootaIds.value.includes(state.selectedPendingNoota.value.external_id)
          "
          @click="requestValidationConfirmation"
        >
          {{ state.config.demoMailFlow ? 'Valider la maquette' : 'Valider et envoyer' }}
        </button>
      </div>
    </section>

    <div
      v-if="showValidationConfirmation"
      class="modal-backdrop modal-backdrop--confirm"
      @click.stop="showValidationConfirmation = false"
    >
      <section class="confirm-modal" @click.stop>
        <div>
          <p class="section-eyebrow">Confirmation</p>
          <h2>Valider ce compte rendu ?</h2>
          <p>
            Le compte rendu sera importe, ajoute a la base et envoye a
            {{ state.pendingNootaRecipientEmail.value.trim() }}.
            {{ state.selectedPendingNootaTaskKeys.value.length }} tache(s) selectionnee(s) seront ajoutees au dossier client.
          </p>
        </div>
        <div class="confirm-modal__actions">
          <button type="button" class="secondary-button" @click="showValidationConfirmation = false">
            Annuler
          </button>
          <button
            type="button"
            class="primary-button"
            :disabled="state.importingPendingNootaIds.value.includes(state.selectedPendingNoota.value.external_id)"
            @click="confirmValidation"
          >
            Confirmer
          </button>
        </div>
      </section>
    </div>
  </div>
</template>
