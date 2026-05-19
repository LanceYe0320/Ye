const { app, BrowserWindow, ipcMain, dialog } = require('electron')
const path = require('path')
const { registerFileHandlers } = require('./services/file-service')
const { registerTerminalHandlers, killAllSessions } = require('./services/terminal-service')
const { registerGitHandlers } = require('./services/git-service')

let mainWindow

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 800,
    minHeight: 600,
    frame: false,
    titleBarStyle: 'hidden',
    backgroundColor: '#1e1e2e',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  global.mainWindow = mainWindow

  const isDev = !app.isPackaged
  if (isDev) {
    mainWindow.loadURL('http://localhost:5173')
    mainWindow.webContents.openDevTools({ mode: 'detach' })
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'))
  }

  mainWindow.on('closed', () => {
    mainWindow = null
    global.mainWindow = null
  })
}

app.whenReady().then(() => {
  // Register all service handlers
  registerFileHandlers(ipcMain)
  registerTerminalHandlers(ipcMain)
  registerGitHandlers(ipcMain)

  // Window control handlers
  ipcMain.handle('select-directory', async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
      properties: ['openDirectory'],
    })
    if (result.canceled) return null
    return result.filePaths[0]
  })

  ipcMain.handle('window-minimize', () => mainWindow?.minimize())
  ipcMain.handle('window-maximize', () => {
    if (mainWindow?.isMaximized()) {
      mainWindow.unmaximize()
    } else {
      mainWindow?.maximize()
    }
  })
  ipcMain.handle('window-close', () => mainWindow?.close())

  createWindow()
})

app.on('window-all-closed', () => {
  killAllSessions()
  app.quit()
})

app.on('before-quit', () => {
  killAllSessions()
})

app.on('activate', () => {
  if (mainWindow === null) createWindow()
})
