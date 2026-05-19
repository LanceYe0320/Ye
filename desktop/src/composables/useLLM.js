import { ref } from 'vue'
import { WSClient } from '../lib/ws-client.js'
import { useConversationStore } from '../stores/conversation.js'

export function useLLM() {
  const wsClient = ref(null)
  const isStreaming = ref(false)
  let intentionalClose = false

  async function sendMessage(content, model = 'glm-4-plus') {
    const store = useConversationStore()

    if (!store.currentConversation) {
      await store.createConversation()
    }

    store.addMessage({
      id: Date.now(),
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    })

    store.resetStreaming()
    isStreaming.value = true
    store.isLoading = true
    intentionalClose = false

    const convId = store.currentConversation.id
    const ws = new WSClient(
      `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/chat/${convId}`
    )

    let assistantContent = ''
    let toolCalls = []

    ws.on('text_delta', (data) => {
      assistantContent += data.text
      store.streamingContent = assistantContent
    })

    ws.on('tool_call_end', (data) => {
      toolCalls.push({
        id: data.tool_call_id,
        name: data.tool_call_name,
        arguments: data.tool_call_arguments,
      })
      store.streamingToolCalls = [...toolCalls]
    })

    ws.on('tool_execution_start', (data) => {
      store.streamingToolCalls.push({
        id: data.tool_call_id,
        name: '',
        status: 'running',
      })
    })

    ws.on('tool_execution_result', (data) => {
      const tc = store.streamingToolCalls.find((t) => t.id === data.tool_call_id)
      if (tc) tc.status = 'done'
    })

    ws.on('done', () => {
      intentionalClose = true
      store.addMessage({
        id: Date.now(),
        role: 'assistant',
        content: assistantContent,
        tool_calls_json: toolCalls.length > 0 ? JSON.stringify(toolCalls) : null,
        created_at: new Date().toISOString(),
      })
      store.resetStreaming()
      isStreaming.value = false
      store.isLoading = false
      ws.disconnect()
    })

    ws.on('error', (data) => {
      intentionalClose = true
      store.addMessage({
        id: Date.now(),
        role: 'assistant',
        content: `[Error] ${data.text || 'Unknown error'}`,
        created_at: new Date().toISOString(),
      })
      isStreaming.value = false
      store.isLoading = false
      ws.disconnect()
    })

    ws.on('disconnected', () => {
      if (isStreaming.value) {
        isStreaming.value = false
        store.isLoading = false
        if (!intentionalClose) {
          store.addMessage({
            id: Date.now(),
            role: 'assistant',
            content: '[Connection lost. Click to retry.]',
            created_at: new Date().toISOString(),
          })
        }
      }
    })

    await ws.connect()
    ws.send({ content, model })

    wsClient.value = ws
  }

  function stopStreaming() {
    intentionalClose = true
    wsClient.value?.disconnect()
    isStreaming.value = false
    const store = useConversationStore()
    store.isLoading = false
  }

  return { sendMessage, stopStreaming, isStreaming }
}
