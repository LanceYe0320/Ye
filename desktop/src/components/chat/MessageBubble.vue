<template>
  <div class="message" :class="message.role">
    <div class="msg-role">{{ roleLabel }}</div>
    <div class="msg-content">
      <div v-if="message.role === 'user'" class="text-content">{{ message.content }}</div>
      <div v-else v-html="renderedContent"></div>
      <div v-if="parsedToolCalls.length > 0" class="tool-calls">
        <div v-for="tc in parsedToolCalls" :key="tc.id" class="tool-call-card">
          <div class="tool-header" @click="toggleTool(tc.id)">
            <span class="tool-icon">&#9881;</span>
            <span class="tool-name">{{ tc.name }}</span>
            <span class="toggle">{{ expanded[tc.id] ? '&#9660;' : '&#9654;' }}</span>
          </div>
          <div v-if="expanded[tc.id]" class="tool-body">
            <pre>{{ JSON.stringify(tc.arguments, null, 2) }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

const props = defineProps({
  message: { type: Object, required: true },
})

const expanded = ref({})

const roleLabel = computed(() => {
  const labels = { user: 'You', assistant: 'Assistant', tool: 'Tool', system: 'System' }
  return labels[props.message.role] || props.message.role
})

const renderedContent = computed(() => DOMPurify.sanitize(md.render(props.message.content || '')))

const parsedToolCalls = computed(() => {
  if (!props.message.tool_calls_json) return []
  try {
    return JSON.parse(props.message.tool_calls_json)
  } catch {
    return []
  }
})

function toggleTool(id) {
  expanded.value[id] = !expanded.value[id]
}
</script>

<style scoped>
.message {
  margin-bottom: 16px;
}
.msg-role {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 4px;
}
.message.user .msg-role { color: var(--success); }
.message.assistant .msg-role { color: var(--accent); }
.message.tool .msg-role { color: var(--warning); }

.msg-content {
  padding: 10px 14px;
  border-radius: 8px;
  line-height: 1.6;
  font-size: 14px;
}
.message.user .msg-content {
  background: rgba(166, 227, 161, 0.1);
  border: 1px solid rgba(166, 227, 161, 0.2);
}
.message.assistant .msg-content {
  background: var(--bg-secondary);
}
.message.tool .msg-content {
  background: rgba(249, 226, 175, 0.1);
  border: 1px solid rgba(249, 226, 175, 0.2);
}

.msg-content :deep(pre) {
  background: var(--bg-tertiary);
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 8px 0;
  font-family: 'Cascadia Code', 'Fira Code', monospace;
  font-size: 13px;
}
.msg-content :deep(code) {
  font-family: 'Cascadia Code', 'Fira Code', monospace;
  font-size: 13px;
}
.msg-content :deep(p) {
  margin: 4px 0;
}
.msg-content :deep(ul), .msg-content :deep(ol) {
  padding-left: 20px;
  margin: 4px 0;
}

.tool-calls {
  margin-top: 8px;
}
.tool-call-card {
  background: var(--bg-tertiary);
  border-radius: 6px;
  margin-top: 4px;
  overflow: hidden;
}
.tool-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 12px;
}
.tool-header:hover { background: var(--border); }
.tool-icon { color: var(--warning); }
.tool-name { color: var(--accent); flex: 1; }
.toggle { color: var(--text-muted); font-size: 10px; }
.tool-body {
  padding: 8px 10px;
  border-top: 1px solid var(--border);
}
.tool-body pre {
  margin: 0;
  font-size: 11px;
  white-space: pre-wrap;
  color: var(--text-secondary);
}
</style>
