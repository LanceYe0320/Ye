<template>
  <div class="title-bar">
    <div class="title-left">
      <span class="app-icon">&#9883;</span>
      <span class="app-title">AI Coding Assistant</span>
    </div>
    <div class="title-center">
      {{ projectStore.currentProject?.name || 'No Project Open' }}
    </div>
    <div class="title-right">
      <span class="status-dot" :class="{ connected: settingsStore.wsConnected }"></span>
    </div>
  </div>
</template>

<script setup>
import { useProjectStore } from '../../stores/project.js'
import { useSettingsStore } from '../../stores/settings.js'

const projectStore = useProjectStore()
const settingsStore = useSettingsStore()
</script>

<style scoped>
.title-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 32px;
  padding: 0 12px;
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border);
  user-select: none;
  -webkit-app-region: drag;
}
.title-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.app-icon {
  font-size: 16px;
  color: var(--accent);
}
.app-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}
.title-center {
  font-size: 12px;
  color: var(--text-muted);
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--error);
}
.status-dot.connected {
  background: var(--success);
}
</style>
