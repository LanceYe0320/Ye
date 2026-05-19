const fs = require('fs').promises
const fsSync = require('fs')
const path = require('path')

function registerFileHandlers(ipcMain) {
  ipcMain.handle('fs:readdir', async (_, dirPath) => {
    const entries = await fs.readdir(dirPath, { withFileTypes: true })
    return entries.map((e) => ({
      name: e.name,
      path: path.join(dirPath, e.name),
      isDir: e.isDirectory(),
      isFile: e.isFile(),
    }))
  })

  ipcMain.handle('fs:readFile', async (_, filePath) => {
    return fs.readFile(filePath, 'utf-8')
  })

  ipcMain.handle('fs:writeFile', async (_, filePath, content) => {
    await fs.mkdir(path.dirname(filePath), { recursive: true })
    await fs.writeFile(filePath, content, 'utf-8')
    return true
  })

  ipcMain.handle('fs:delete', async (_, targetPath) => {
    const stat = await fs.stat(targetPath)
    if (stat.isDirectory()) {
      await fs.rm(targetPath, { recursive: true, force: true })
    } else {
      await fs.unlink(targetPath)
    }
    return true
  })

  ipcMain.handle('fs:stat', async (_, filePath) => {
    const stat = await fs.stat(filePath)
    return {
      size: stat.size,
      isDir: stat.isDirectory(),
      isFile: stat.isFile(),
      mtime: stat.mtime.toISOString(),
    }
  })

  ipcMain.handle('fs:mkdir', async (_, dirPath) => {
    await fs.mkdir(dirPath, { recursive: true })
    return true
  })

  ipcMain.handle('fs:exists', async (_, targetPath) => {
    try {
      await fs.access(targetPath)
      return true
    } catch {
      return false
    }
  })

  ipcMain.handle('fs:rename', async (_, oldPath, newPath) => {
    await fs.rename(oldPath, newPath)
    return true
  })

  ipcMain.handle('fs:watch', (_, watchPath) => {
    try {
      const watcher = fsSync.watch(watchPath, { recursive: true }, (event, filename) => {
        if (global.mainWindow && !global.mainWindow.isDestroyed()) {
          global.mainWindow.webContents.send('fs:change', { event, filename, path: watchPath })
        }
      })
      return true
    } catch {
      return false
    }
  })
}

module.exports = { registerFileHandlers }
