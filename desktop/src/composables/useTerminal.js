import { ref } from 'vue'

const isElectron = () => !!window.electronAPI?.pty

export function useTerminal(projectId) {
  const output = ref('')
  const isRunning = ref(false)
  const error = ref('')
  const ptySessionId = ref(null)
  let listenersRegistered = false

  // --- Electron PTY mode ---

  function onData(data) {
    if (data.id === ptySessionId.value) {
      output.value += data.data
    }
  }

  function onExit(data) {
    if (data.id === ptySessionId.value) {
      isRunning.value = false
      ptySessionId.value = null
    }
  }

  async function startPtySession(cwd) {
    const id = `pty-${Date.now()}`
    const result = await window.electronAPI.pty.create({ id, cwd })
    if (!result.ok) {
      error.value = result.error || 'Failed to create PTY session'
      return null
    }
    ptySessionId.value = id
    if (!listenersRegistered) {
      window.electronAPI.pty.onData(onData)
      window.electronAPI.pty.onExit(onExit)
      listenersRegistered = true
    }
    return id
  }

  async function ptyExecute(command) {
    if (!ptySessionId.value) return
    isRunning.value = true
    output.value = ''
    await window.electronAPI.pty.write(ptySessionId.value, command + '\n')
  }

  async function ptyResize(cols, rows) {
    if (ptySessionId.value) {
      await window.electronAPI.pty.resize(ptySessionId.value, cols, rows)
    }
  }

  async function ptyKill() {
    if (ptySessionId.value) {
      await window.electronAPI.pty.kill(ptySessionId.value)
      ptySessionId.value = null
      isRunning.value = false
    }
  }

  // --- HTTP fallback ---

  async function httpExecute(command, { timeout } = {}) {
    isRunning.value = true
    error.value = ''
    output.value = ''

    try {
      const body = { command }
      if (timeout) body.timeout = timeout

      const res = await fetch(`/api/projects/${projectId.value || projectId}/terminal/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()

      if (data.exit_code !== 0) {
        error.value = data.stderr || `Exit code: ${data.exit_code}`
      }
      output.value = data.stdout || ''
      if (data.stderr) {
        output.value += `\n[stderr]\n${data.stderr}`
      }
      return data
    } catch (e) {
      error.value = e.message
      return { exit_code: -1, stdout: '', stderr: e.message }
    } finally {
      isRunning.value = false
    }
  }

  // --- Unified API ---

  async function execute(command, opts = {}) {
    if (isElectron()) {
      if (!ptySessionId.value) {
        const cwd = opts.cwd || (projectId.value ? `/projects/${projectId.value}` : undefined)
        await startPtySession(cwd)
      }
      return ptyExecute(command)
    }
    return httpExecute(command, opts)
  }

  function dispose() {
    if (isElectron()) {
      ptyKill()
    }
  }

  return { output, isRunning, error, ptySessionId, execute, resize: ptyResize, kill: ptyKill, dispose }
}
