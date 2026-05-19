<template>
  <div class="diff-viewer">
    <div class="diff-header">
      <span class="diff-title">Changes</span>
      <div class="diff-actions">
        <button class="btn-accept" @click="$emit('accept', patchedContent)">Apply</button>
        <button class="btn-reject" @click="$emit('reject')">Dismiss</button>
      </div>
    </div>
    <div ref="diffContainer" class="diff-content"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as monaco from 'monaco-editor'

const props = defineProps({
  original: { type: String, default: '' },
  modified: { type: String, default: '' },
  language: { type: String, default: 'plaintext' },
})

const emit = defineEmits(['accept', 'reject'])

const diffContainer = ref(null)
let diffEditor = null

const patchedContent = ref(props.modified)

onMounted(() => {
  diffEditor = monaco.editor.createDiffEditor(diffContainer.value, {
    theme: 'vs-dark',
    readOnly: true,
    renderSideBySide: true,
    automaticLayout: true,
    fontSize: 13,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
  })

  updateDiff()
})

function updateDiff() {
  if (!diffEditor) return
  const originalModel = monaco.editor.createModel(props.original, props.language)
  const modifiedModel = monaco.editor.createModel(props.modified, props.language)
  diffEditor.setModel({ original: originalModel, modified: modifiedModel })
  patchedContent.value = props.modified
}

watch(() => [props.original, props.modified], updateDiff)

onBeforeUnmount(() => {
  diffEditor?.dispose()
})
</script>

<style scoped>
.diff-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.diff-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-primary);
  flex-shrink: 0;
}
.diff-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.diff-actions {
  display: flex;
  gap: 8px;
}
.btn-accept, .btn-reject {
  padding: 4px 12px;
  border-radius: 4px;
  border: none;
  font-size: 12px;
  cursor: pointer;
  font-weight: 500;
}
.btn-accept {
  background: var(--accent-primary);
  color: #fff;
}
.btn-accept:hover {
  filter: brightness(1.1);
}
.btn-reject {
  background: var(--bg-hover);
  color: var(--text-secondary);
  border: 1px solid var(--border-primary);
}
.btn-reject:hover {
  background: var(--border-primary);
}
.diff-content {
  flex: 1;
  overflow: hidden;
}
</style>
