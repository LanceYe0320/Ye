export class LLMClient {
  constructor(baseUrl = '') {
    this.baseUrl = baseUrl
  }

  async *streamChat({ conversationId, content, model = 'glm-4-plus' }) {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${location.host}/ws/chat/${conversationId}`

    const ws = new WebSocket(url)
    let resolveOpen
    const openPromise = new Promise((r) => { resolveOpen = r })

    ws.onopen = () => resolveOpen()

    const messageQueue = []
    let resolveMessage = null

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (resolveMessage) {
        resolveMessage(data)
        resolveMessage = null
      } else {
        messageQueue.push(data)
      }
    }

    await openPromise
    ws.send(JSON.stringify({ content, model }))

    while (true) {
      const msg = messageQueue.length > 0
        ? messageQueue.shift()
        : await new Promise((r) => { resolveMessage = r })

      if (msg.type === 'done') {
        ws.close()
        return
      }
      if (msg.type === 'error') {
        ws.close()
        throw new Error(msg.text || 'LLM error')
      }
      yield msg
    }
  }

  async sendMessage({ conversationId, content, model }) {
    let fullText = ''
    const toolCalls = []

    for await (const chunk of this.streamChat({ conversationId, content, model })) {
      if (chunk.type === 'text_delta') {
        fullText += chunk.text
      } else if (chunk.type === 'tool_call_end') {
        toolCalls.push({
          id: chunk.tool_call_id,
          name: chunk.tool_call_name,
          arguments: chunk.tool_call_arguments,
        })
      }
    }

    return { content: fullText, toolCalls }
  }
}
