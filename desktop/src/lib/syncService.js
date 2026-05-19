/**
 * Singleton sync service — one WebSocket connection to /ws/sync,
 * multiple document subscriptions.
 */

class SyncService {
  constructor() {
    this.ws = null
    this.subscriptions = new Map() // docId → Set<callback>
    this.connected = false
    this.retryCount = 0
    this.MAX_RETRIES = 10
    this.reconnectTimer = null
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) return

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    this.ws = new WebSocket(`${protocol}//${location.host}/ws/sync`)

    this.ws.onopen = () => {
      this.connected = true
      this.retryCount = 0
      for (const docId of this.subscriptions.keys()) {
        this.ws.send(JSON.stringify({ type: 'subscribe', doc_id: docId }))
      }
    }

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'sync_full' || msg.type === 'sync_update') {
          const callbacks = this.subscriptions.get(msg.doc_id)
          if (callbacks) {
            for (const cb of callbacks) cb(msg)
          }
        }
      } catch {
        // ignore malformed messages
      }
    }

    this.ws.onclose = () => {
      this.connected = false
      this._attemptReconnect()
    }

    this.ws.onerror = () => {
      this.connected = false
    }
  }

  _attemptReconnect() {
    if (this.retryCount >= this.MAX_RETRIES) return
    this.retryCount++
    const delay = Math.min(3000 * this.retryCount, 30000)
    this.reconnectTimer = setTimeout(() => this.connect(), delay)
  }

  subscribe(docId, callback) {
    if (!this.subscriptions.has(docId)) {
      this.subscriptions.set(docId, new Set())
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'subscribe', doc_id: docId }))
      } else {
        this.connect()
      }
    }
    this.subscriptions.get(docId).add(callback)
  }

  unsubscribe(docId, callback) {
    const callbacks = this.subscriptions.get(docId)
    if (!callbacks) return
    callbacks.delete(callback)
    if (callbacks.size === 0) {
      this.subscriptions.delete(docId)
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'unsubscribe', doc_id: docId }))
      }
    }
  }

  sendUpdate(docId, update) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'sync_update', doc_id: docId, update }))
    }
  }

  disconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.ws?.close()
    this.subscriptions.clear()
    this.connected = false
  }
}

export const syncService = new SyncService()
