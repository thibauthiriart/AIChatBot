<script setup lang="ts">
import { formatConversationDate, formatDateTimeWithTimezone, useAgentiaState } from '../composables/useAgentiaState'

const state = useAgentiaState()
</script>

<template>
  <div
    v-if="state.selectedPendingNoota.value"
    class="modal-backdrop"
    @click="state.closePendingNootaPreview()"
  >
    <section class="modal-card" @click.stop>
      <div class="modal-card__header">
        <div>
          <p class="section-eyebrow">Validation</p>
          <h2>{{ state.selectedPendingNoota.value.meeting_title }}</h2>
        </div>
        <button type="button" class="modal-card__close" @click="state.closePendingNootaPreview()">Fermer</button>
      </div>

      <div class="modal-card__meta">
        <span>{{ state.selectedPendingNoota.value.client_name }}</span>
        <span v-if="state.selectedPendingNoota.value.project_name">{{ state.selectedPendingNoota.value.project_name }}</span>
        <span v-if="state.selectedPendingNoota.value.meeting_at">
          {{ formatConversationDate(state.selectedPendingNoota.value.meeting_at) }}
        </span>
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
            !state.pendingNootaRecipientEmail.value.trim() ||
            state.importingPendingNootaIds.value.includes(state.selectedPendingNoota.value.external_id)
          "
          @click="state.importPendingNootaReport(state.selectedPendingNoota.value)"
        >
          {{ state.config.demoMailFlow ? 'Valider la maquette' : 'Valider et envoyer' }}
        </button>
      </div>
    </section>
  </div>
</template>
