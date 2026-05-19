<template>
  <div class="file-tree">
    <div class="tree-header">
      <span>Explorer</span>
    </div>
    <div class="tree-content">
      <div v-if="loading" class="loading">Loading...</div>
      <FileTreeNode
        v-for="entry in files"
        :key="entry.path"
        :entry="entry"
        :project-id="projectStore.currentProjectId"
        :depth="0"
        @select="handleSelect"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useProjectStore } from '../../stores/project.js'
import { useFileSystem } from '../../composables/useFileSystem.js'
import FileTreeNode from './FileTreeNode.vue'

const projectStore = useProjectStore()
const { listFiles } = useFileSystem()

const files = ref([])
const loading = ref(false)

async function loadFiles() {
  if (!projectStore.currentProject) return
  loading.value = true
  try {
    files.value = await listFiles(projectStore.currentProjectId)
  } catch (e) {
    console.error('Failed to load files:', e)
  }
  loading.value = false
}

function handleSelect(entry) {
  projectStore.openFile(entry)
}

onMounted(loadFiles)
watch(() => projectStore.currentProjectId, loadFiles)
</script>

<style scoped>
.file-tree {
  width: 220px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.tree-header {
  padding: 8px 12px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border);
}
.tree-content {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}
.loading {
  padding: 12px;
  color: var(--text-muted);
  font-size: 12px;
}
</style>
