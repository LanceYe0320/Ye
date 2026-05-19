const path = require('path')
const os = require('os')
const { EventEmitter } = require('events')

let pty = null
const sessions = new Map()

function registerTerminalHandlers(ipcMain) {
  ipcMain.handle('pty:create', async (_, { id, cwd, shell } = {}) => {
    try {
      if (!pty) pty = require('node-pty')
    } catch {
      return { ok: false, error: 'node-pty not installed. Run: npm install node-pty' }
    }

    const defaultShell =
      shell || process.env.COMSPEC || (os.platform() === 'win32' ? 'cmd.exe' : process.env.SHELL || '/bin/sh')

    const ptyProcess = pty.spawn(defaultShell, [], {
      name: 'xterm-256color',
      cols: 120,
      rows: 30,
      cwd: cwd || os.homedir(),
      env: { ...process.env },
    })

    sessions.set(id, { process: ptyProcess, emitter: new EventEmitter() })

    ptyProcess.onData((data) => {
      if (global.mainWindow && !global.mainWindow.isDestroyed()) {
        global.mainWindow.webContents.send('pty:data', { id, data })
      }
    })

    ptyProcess.onExit(({ exitCode }) => {
      sessions.delete(id)
      if (global.mainWindow && !global.mainWindow.isDestroyed()) {
        global.mainWindow.webContents.send('pty:exit', { id, exitCode })
      }
    })

    return { ok: true, pid: ptyProcess.pid }
  })

  ipcMain.handle('pty:write', (_, { id, data }) => {
    const session = sessions.get(id)
    if (session) {
      session.process.write(data)
      return true
    }
    return false
  })

  ipcMain.handle('pty:resize', (_, { id, cols, rows }) => {
    const session = sessions.get(id)
    if (session) {
      try {
        session.process.resize(cols, rows)
      } catch {}
      return true
    }
    return false
  })

  ipcMain.handle('pty:kill', (_, { id }) => {
    const session = sessions.get(id)
    if (session) {
      session.process.kill()
      sessions.delete(id)
      return true
    }
    return false
  })

  ipcMain.handle('pty:list', () => {
    return Array.from(sessions.keys())
  })
}

function killAllSessions() {
  for (const [id, session] of sessions) {
    try {
      session.process.kill()
    } catch {}
  }
  sessions.clear()
}

module.exports = { registerTerminalHandlers, killAllSessions }
