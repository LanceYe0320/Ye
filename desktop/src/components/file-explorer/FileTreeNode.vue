<template>
  <div>
    <div class="tree-node" :style="{ paddingLeft: depth * 16 + 8 + 'px' }" @click="handleClick">
      <span v-if="entry.is_dir" class="arrow">{{ expanded ? '&#9660;' : '&#9654;' }}</span>
      <span v-else class="arrow-spacer"></span>
      <span class="icon">{{ entry.is_dir ? '&#128193;' : getFileIcon(entry.name) }}</span>
      <span class="name">{{ entry.name }}</span>
    </div>
    <div v-if="entry.is_dir && expanded" class="children">
      <FileTreeNode
        v-for="child in children"
        :key="child.path"
        :entry="child"
        :project-id="projectId"
        :depth="depth + 1"
        @select="$emit('select', $event)"
      />
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useFileSystem } from '../../composables/useFileSystem.js'

const props = defineProps({
  entry: { type: Object, required: true },
  projectId: { type: Number, required: true },
  depth: { type: Number, default: 0 },
})
const emit = defineEmits(['select'])

const { listFiles } = useFileSystem()
const expanded = ref(false)
const children = ref([])

async function handleClick() {
  if (props.entry.is_dir) {
    expanded.value = !expanded.value
    if (expanded.value && children.value.length === 0) {
      children.value = await listFiles(props.entry.path)
    }
  } else {
    emit('select', props.entry)
  }
}

function getFileIcon(name) {
  const ext = name.split('.').pop()?.toLowerCase()
  const icons = {
    js: '&#128220;', ts: '&#128220;', py: '&#128013;', java: '&#9749;',
    vue: '&#128202;', html: '&#127760;', css: '&#127912;', json: '&#128218;',
    md: '&#128196;', txt: '&#128196;', yml: '&#128218;', yaml: '&#128218;',
    rs: '&#9881;', go: '&#128051;', cpp: '&#9889;', c: '&#9889;',
  }
  return icons[ext] || '&#128196;'
}
</script>

<style scoped>
.tree-node {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
  user-select: none;
}
.tree-node:hover {
  background: var(--border);
  color: var(--text-primary);
}
.arrow, .arrow-spacer {
  width: 12px;
  font-size: 8px;
  color: var(--text-muted);
  text-align: center;
}
.arrow-spacer {
  visibility: hidden;
}
.icon {
  font-size: 14px;
  font-style: normal;
}
.name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
