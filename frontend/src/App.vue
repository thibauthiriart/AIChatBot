<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useAgentiaState } from './composables/useAgentiaState'
import ConnectorsView from './components/ConnectorsView.vue'
import ConversationHistory from './components/ConversationHistory.vue'
import DashboardView from './components/DashboardView.vue'
import ClientsProjectsView from './components/ClientsProjectsView.vue'
import DriveMonitoringView from './components/DriveMonitoringView.vue'
import NotificationCenter from './components/NotificationCenter.vue'
import OfferProposalsView from './components/OfferProposalsView.vue'
import PendingReportModal from './components/PendingReportModal.vue'

const state = useAgentiaState()

type PageId = 'dashboard' | 'clients' | 'drive' | 'connectors' | 'offers'

function pageFromHash(hash: string): PageId {
  if (hash === '#/clients') {
    return 'clients'
  }

  if (hash === '#/connectors') {
    return 'connectors'
  }

  if (hash === '#/offers') {
    return 'offers'
  }

  return hash === '#/drive' ? 'drive' : 'dashboard'
}

const currentPage = ref<PageId>(pageFromHash(window.location.hash))

function syncPageFromHash() {
  currentPage.value = pageFromHash(window.location.hash)
}

function navigate(page: PageId) {
  if (page === 'clients') {
    window.location.hash = '/clients'
    return
  }

  if (page === 'drive') {
    window.location.hash = '/drive'
    return
  }

  if (page === 'connectors') {
    window.location.hash = '/connectors'
    return
  }

  if (page === 'offers') {
    window.location.hash = '/offers'
    return
  }

  window.location.hash = '/dashboard'
}

const currentView = computed(() => {
  if (currentPage.value === 'clients') {
    return ClientsProjectsView
  }

  if (currentPage.value === 'drive') {
    return DriveMonitoringView
  }

  if (currentPage.value === 'connectors') {
    return ConnectorsView
  }

  if (currentPage.value === 'offers') {
    return OfferProposalsView
  }

  return DashboardView
})

const showConversationSidebar = computed(() => currentPage.value !== 'offers')

onMounted(() => {
  if (!window.location.hash) {
    window.location.hash = '/dashboard'
  }
  syncPageFromHash()
  window.addEventListener('hashchange', syncPageFromHash)
  void state.startPolling()
})

onBeforeUnmount(() => {
  window.removeEventListener('hashchange', syncPageFromHash)
  state.stopPolling()
})
</script>

<template>
  <section class="app-frame">
    <NotificationCenter />
    <PendingReportModal />

    <header class="topbar">
      <div>
        <p class="section-eyebrow">AgentIA</p>
        <h1>{{ state.config.title }}</h1>
      </div>

      <nav class="topbar__nav" aria-label="Navigation principale">
        <button
          type="button"
          class="topbar__link"
          :class="{ 'topbar__link--active': currentPage === 'dashboard' }"
          @click="navigate('dashboard')"
        >
          Dashboard
        </button>
        <button
          type="button"
          class="topbar__link"
          :class="{ 'topbar__link--active': currentPage === 'offers' }"
          @click="navigate('offers')"
        >
          Propositions d'offres
        </button>
        <button
          type="button"
          class="topbar__link"
          :class="{ 'topbar__link--active': currentPage === 'clients' }"
          @click="navigate('clients')"
        >
          Clients
        </button>
        <button
          type="button"
          class="topbar__link"
          :class="{ 'topbar__link--active': currentPage === 'drive' }"
          @click="navigate('drive')"
        >
          Surveillance Drive
        </button>
        <button
          type="button"
          class="topbar__link"
          :class="{ 'topbar__link--active': currentPage === 'connectors' }"
          @click="navigate('connectors')"
        >
          Connecteurs
        </button>
      </nav>
    </header>

    <div class="workspace" :class="{ 'workspace--full': !showConversationSidebar }">
      <aside v-if="showConversationSidebar" class="workspace__sidebar">
        <ConversationHistory />
      </aside>

      <main class="workspace__main">
        <component :is="currentView" />
      </main>
    </div>
  </section>
</template>
