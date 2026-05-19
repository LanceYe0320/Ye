<template>
  <div class="chat-panel">
    <div class="chat-header">
      <span>AI Chat</span>
      <span class="model-badge">{{ settingsStore.settings.model }}</span>
    </div>
    <div class="messages" ref="messagesContainer">
      <div v-if="conversationStore.messages.length === 0" class="empty-state">
        <p>Start a conversation with AI</p>
        <p class="hint">Ask me to read files, run commands, or write code</p>
      </div>
      <MessageBubble
        v-for="msg in conversationStore.messages"
        :key="msg.id"
        :message="msg"
      />
      <div v-if="conversationStore.isLoading" class="streaming-msg">
        <div class="msg-role assistant">Assistant</div>
        <div class="msg-content">
          <div v-html="renderMarkdown(conversationStore.streamingContent || 'Thinking...')"></div>
          <div v-for="tc in conversationStore.streamingToolCalls" :key="tc.id" class="tool-call-inline">
            <span class="tool-name">{{ tc.name || 'Running...' }}</span>
            <span class="tool-status">{{ tc.status === 'running' ? '...' : 'done' }}</span>
          </div>
        </div>
      </div>
    </div>
    <div class="input-area">
      <textarea
        v-model="inputText"
        @keydown.enter.exact.prevent="handleSend"
        placeholder="Send a message... (Enter to send, Shift+Enter for newline)"
        rows="3"
      ></textarea>
      <button class="send-btn" @click="handleSend" :disabled="!inputText.trim() || conversationStore.isLoading">
        <span v-if="conversationStore.isLoading" @click.stop="stopStreaming">&#9632;</span>
        <span v-else>&#8593;</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, watch } from 'vue'
import { useConversationStore } from '../../stores/conversation.js'
import { useSettingsStore } from '../../stores/settings.js'
import { useLLM } from '../../composables/useLLM.js'
import MessageBubble from './MessageBubble.vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const conversationStore = useConversationStore()
const settingsStore = useSettingsStore()
const { sendMessage, stopStreaming } = useLLM()

const inputText = ref('')
const messagesContainer = ref(null)

function renderMarkdown(text) {
  const raw = md.render(text || '')
  return DOMPurify.sanitize(raw)
}

async function handleSend() {
  const text = inputText.value.trim()
  if (!text) return
  inputText.value = ''

  if (!conversationStore.currentConversation) {
    await conversationStore.createConversation()
  }

  await sendMessage(text, settingsStore.settings.model)
  await nextTick()
  scrollToBottom()
}

function scrollToBottom() {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

watch(
  () => conversationStore.messages.length,
  () => nextTick(scrollToBottom)
)

watch(
  () => conversationStore.streamingContent,
  () => nextTick(scrollToBottom)
)
</script>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  border-left: 1px solid var(--border);
  background: var(--bg-primary);
}
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border);
  font-weight: 600;
  font-size: 13px;
}
.model-badge {
  font-size: 11px;
  padding: 2px 8px;
  background: var(--bg-secondary);
  border-radius: 4px;
  color: var(--accent);
  font-weight: 500;
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
.empty-state {
  text-align: center;
  color: var(--text-muted);
  padding: 40px 20px;
}
.empty-state .hint {
  font-size: 12px;
  margin-top: 8px;
}
.streaming-msg {
  margin-bottom: 16px;
}
.msg-role {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
  margin-bottom: 4px;
}
.msg-content {
  padding: 8px 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.6;
}
.tool-call-inline {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  margin: 4px 4px 0 0;
  background: var(--bg-tertiary);
  border-radius: 4px;
  font-size: 12px;
}
.tool-name {
  color: var(--warning);
}
.tool-status {
  color: var(--text-muted);
}
.input-area {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid var(--border);
}
textarea {
  flex: 1;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-primary);
  padding: 10px 12px;
  font-size: 14px;
  font-family: inherit;
  resize: none;
  outline: none;
}
textarea:focus {
  border-color: var(--accent);
}
.send-btn {
  width: 36px;
  height: 36px;
  background: var(--accent);
  color: var(--bg-tertiary);
  border: none;
  border-radius: 8px;
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.send-btn:disabled {
  opacity: 0.4;
  cursor: default;
}
.send-btn:hover:not(:disabled) {
  background: var(--accent-hover);
}
</style>
