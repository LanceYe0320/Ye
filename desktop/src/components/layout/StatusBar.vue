<template>
  <div class="status-bar">
    <span class="status-item">
      <span class="dot" :class="statusClass"></span>
      {{ statusText }}
    </span>
    <span class="status-item">{{ settingsStore.settings.model }}</span>
    <span class="status-item">GLM-4</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useSettingsStore } from '../../stores/settings.js'
import { useConversationStore } from '../../stores/conversation.js'

const settingsStore = useSettingsStore()
const conversationStore = useConversationStore()

const statusText = computed(() => {
  if (conversationStore.isLoading) return 'AI Thinking...'
  return settingsStore.wsConnected ? 'Connected' : 'Local'
})

const statusClass = computed(() => ({
  connected: settingsStore.wsConnected,
  loading: conversationStore.isLoading,
}))
</script>

<style scoped>
.status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 24px;
  padding: 0 12px;
  background: var(--accent);
  color: var(--bg-tertiary);
  font-size: 12px;
  font-weight: 500;
}
.status-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--bg-tertiary);
}
.dot.connected {
  background: var(--success);
}
.dot.loading {
  background: var(--warning);
  animation: pulse 1s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
