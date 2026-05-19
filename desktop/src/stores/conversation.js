import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiFetch } from '../lib/api.js'
import { syncService } from '../lib/syncService.js'

let _syncDocId = null
let _syncCallback = null

function _unsubscribeSync() {
  if (_syncDocId && _syncCallback) {
    syncService.unsubscribe(_syncDocId, _syncCallback)
    _syncDocId = null
    _syncCallback = null
  }
}

export const useConversationStore = defineStore('conversation', () => {
  const conversations = ref([])
  const currentConversation = ref(null)
  const messages = ref([])
  const isLoading = ref(false)
  const streamingContent = ref('')
  const streamingToolCalls = ref([])

  async function fetchConversations() {
    try {
      const res = await apiFetch('/api/conversations/')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      conversations.value = await res.json()
    } catch (e) {
      console.error('Failed to fetch conversations:', e)
    }
  }

  async function createConversation(title = 'New Conversation', projectId = null, model = 'glm-4-plus') {
    try {
      const res = await apiFetch('/api/conversations/', {
        method: 'POST',
        body: JSON.stringify({ title, project_id: projectId, model }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const conv = await res.json()
      conversations.value.unshift(conv)
      currentConversation.value = conv
      messages.value = []
      return conv
    } catch (e) {
      console.error('Failed to create conversation:', e)
      throw e
    }
  }

  async function selectConversation(conv) {
    _unsubscribeSync()
    currentConversation.value = conv
    try {
      const res = await apiFetch(`/api/conversations/${conv.id}/messages/`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      messages.value = await res.json()
    } catch (e) {
      console.error('Failed to load messages:', e)
    }
    _syncDocId = `chat:${conv.id}`
    _syncCallback = () => {
      apiFetch(`/api/conversations/${conv.id}/messages/`)
        .then((r) => (r.ok ? r.json() : []))
        .then((data) => { messages.value = data })
        .catch(() => {})
    }
    syncService.subscribe(_syncDocId, _syncCallback)
  }

  async function deleteConversation(id) {
    _unsubscribeSync()
    try {
      await apiFetch(`/api/conversations/${id}`, { method: 'DELETE' })
      conversations.value = conversations.value.filter((c) => c.id !== id)
      if (currentConversation.value?.id === id) {
        currentConversation.value = null
        messages.value = []
      }
    } catch (e) {
      console.error('Failed to delete conversation:', e)
    }
  }

  function addMessage(msg) {
    messages.value.push(msg)
    if (_syncDocId) {
      syncService.sendUpdate(_syncDocId, {
        last_role: msg.role,
        updated_at: new Date().toISOString(),
      })
    }
  }

  function resetStreaming() {
    streamingContent.value = ''
    streamingToolCalls.value = []
  }

  return {
    conversations, currentConversation, messages, isLoading,
    streamingContent, streamingToolCalls,
    fetchConversations, createConversation, selectConversation,
    deleteConversation, addMessage, resetStreaming,
  }
})
