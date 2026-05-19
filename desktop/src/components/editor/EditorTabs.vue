<template>
  <div class="editor-tabs" v-if="openFiles.length > 0">
    <div
      v-for="file in openFiles"
      :key="file.path"
      :class="['tab', { active: file.path === activeFilePath }]"
      @click="selectFile(file)"
    >
      <span class="tab-icon">{{ fileIcon(file.name) }}</span>
      <span class="tab-name" :title="file.path">{{ file.name }}</span>
      <span class="tab-modified" v-if="file.modified">●</span>
      <button class="tab-close" @click.stop="closeFile(file.path)">×</button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useProjectStore } from '../../stores/project.js'

const store = useProjectStore()
const openFiles = computed(() => store.openFiles)
const activeFilePath = computed(() => store.activeFile?.path)

function selectFile(file) {
  store.openFile(file)
}

function closeFile(path) {
  store.closeFile(path)
}

function fileIcon(name) {
  const ext = name?.split('.').pop().toLowerCase()
  const icons = {
    js: 'JS', jsx: 'JS', ts: 'TS', tsx: 'TS', py: 'PY', java: 'JV',
    html: 'HT', css: 'CS', json: 'JS', md: 'MD', vue: 'VU', dart: 'DA',
    rs: 'RS', go: 'GO', rb: 'RB', php: 'PH', sql: 'DB', yaml: 'YL', yml: 'YL',
  }
  return icons[ext] || 'FI'
}
</script>

<style scoped>
.editor-tabs {
  display: flex;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-primary);
  overflow-x: auto;
  flex-shrink: 0;
  height: 36px;
}
.tab {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 12px;
  cursor: pointer;
  border-right: 1px solid var(--border-primary);
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
  min-width: 0;
  transition: background 0.15s;
}
.tab:hover {
  background: var(--bg-hover);
}
.tab.active {
  background: var(--bg-primary);
  color: var(--text-primary);
  border-bottom: 2px solid var(--accent-primary);
}
.tab-icon {
  font-size: 11px;
  opacity: 0.6;
  font-weight: 600;
}
.tab-name {
  overflow: hidden;
  text-overflow: ellipsis;
}
.tab-modified {
  color: var(--accent-warning);
  font-size: 8px;
}
.tab-close {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
  padding: 0 2px;
  border-radius: 3px;
  opacity: 0;
  transition: opacity 0.15s;
}
.tab:hover .tab-close {
  opacity: 1;
}
.tab-close:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
</style>
