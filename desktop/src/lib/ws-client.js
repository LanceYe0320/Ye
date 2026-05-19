export class WSClient {
  constructor(url) {
    this.url = url
    this.ws = null
    this.handlers = new Map()
    this.reconnectAttempts = 0
    this.maxReconnectAttempts = 10
    this.reconnectDelay = 1000
  }

  connect() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.url)

      this.ws.onopen = () => {
        this.reconnectAttempts = 0
        this.emit('connected')
        resolve()
      }

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          this.emit(data.type, data)
        } catch (e) {
          console.error('WS parse error:', e)
        }
      }

      this.ws.onclose = () => {
        this.emit('disconnected')
        this.attemptReconnect()
      }

      this.ws.onerror = (err) => {
        this.emit('error', err)
        reject(err)
      }
    })
  }

  send(data) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    }
  }

  on(event, handler) {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, [])
    }
    this.handlers.get(event).push(handler)
  }

  off(event, handler) {
    const handlers = this.handlers.get(event)
    if (handlers) {
      this.handlers.set(event, handlers.filter((h) => h !== handler))
    }
  }

  emit(event, data) {
    const handlers = this.handlers.get(event)
    if (handlers) {
      handlers.forEach((h) => h(data))
    }
  }

  attemptReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return
    this.reconnectAttempts++
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1)
    setTimeout(() => this.connect(), delay)
  }

  disconnect() {
    this.maxReconnectAttempts = 0
    this.ws?.close()
  }
}
