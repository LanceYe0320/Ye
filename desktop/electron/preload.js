const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  // Window controls
  selectDirectory: () => ipcRenderer.invoke('select-directory'),
  minimizeWindow: () => ipcRenderer.invoke('window-minimize'),
  maximizeWindow: () => ipcRenderer.invoke('window-maximize'),
  closeWindow: () => ipcRenderer.invoke('window-close'),

  // File system
  fs: {
    readdir: (dirPath) => ipcRenderer.invoke('fs:readdir', dirPath),
    readFile: (filePath) => ipcRenderer.invoke('fs:readFile', filePath),
    writeFile: (filePath, content) => ipcRenderer.invoke('fs:writeFile', filePath, content),
    delete: (targetPath) => ipcRenderer.invoke('fs:delete', targetPath),
    stat: (filePath) => ipcRenderer.invoke('fs:stat', filePath),
    mkdir: (dirPath) => ipcRenderer.invoke('fs:mkdir', dirPath),
    exists: (targetPath) => ipcRenderer.invoke('fs:exists', targetPath),
    rename: (oldPath, newPath) => ipcRenderer.invoke('fs:rename', oldPath, newPath),
    watch: (watchPath) => ipcRenderer.invoke('fs:watch', watchPath),
    onChange: (callback) => ipcRenderer.on('fs:change', (_, data) => callback(data)),
  },

  // Terminal (PTY)
  pty: {
    create: (opts) => ipcRenderer.invoke('pty:create', opts),
    write: (id, data) => ipcRenderer.invoke('pty:write', { id, data }),
    resize: (id, cols, rows) => ipcRenderer.invoke('pty:resize', { id, cols, rows }),
    kill: (id) => ipcRenderer.invoke('pty:kill', { id }),
    list: () => ipcRenderer.invoke('pty:list'),
    onData: (callback) => ipcRenderer.on('pty:data', (_, data) => callback(data)),
    onExit: (callback) => ipcRenderer.on('pty:exit', (_, data) => callback(data)),
  },

  // Git
  git: {
    status: (repoPath) => ipcRenderer.invoke('git:status', repoPath),
    log: (repoPath, count) => ipcRenderer.invoke('git:log', repoPath, count),
    diff: (repoPath, opts) => ipcRenderer.invoke('git:diff', repoPath, opts),
    branches: (repoPath) => ipcRenderer.invoke('git:branches', repoPath),
    commit: (repoPath, opts) => ipcRenderer.invoke('git:commit', repoPath, opts),
    checkout: (repoPath, opts) => ipcRenderer.invoke('git:checkout', repoPath, opts),
    fetch: (repoPath) => ipcRenderer.invoke('git:fetch', repoPath),
    pull: (repoPath) => ipcRenderer.invoke('git:pull', repoPath),
    push: (repoPath) => ipcRenderer.invoke('git:push', repoPath),
    init: (repoPath) => ipcRenderer.invoke('git:init', repoPath),
    isRepo: (repoPath) => ipcRenderer.invoke('git:isRepo', repoPath),
  },
})
