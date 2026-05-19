import { ref } from 'vue'

const isElectron = () => !!window.electronAPI?.fs

export function useFileSystem() {
  const loading = ref(false)

  async function listFiles(dirPath) {
    if (isElectron()) {
      return window.electronAPI.fs.readdir(dirPath)
    }
    // Fallback: not available without project context
    return []
  }

  async function readFile(filePath) {
    if (isElectron()) {
      return window.electronAPI.fs.readFile(filePath)
    }
    const res = await fetch(`/api/files/${filePath}`)
    return (await res.json()).content
  }

  async function writeFile(filePath, content) {
    if (isElectron()) {
      return window.electronAPI.fs.writeFile(filePath, content)
    }
    const res = await fetch(`/api/files/${filePath}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    })
    return res.json()
  }

  async function deleteFile(filePath) {
    if (isElectron()) {
      return window.electronAPI.fs.delete(filePath)
    }
    const res = await fetch(`/api/files/${filePath}`, { method: 'DELETE' })
    return res.json()
  }

  async function stat(filePath) {
    if (isElectron()) {
      return window.electronAPI.fs.stat(filePath)
    }
    return null
  }

  async function mkdir(dirPath) {
    if (isElectron()) {
      return window.electronAPI.fs.mkdir(dirPath)
    }
    return null
  }

  async function exists(filePath) {
    if (isElectron()) {
      return window.electronAPI.fs.exists(filePath)
    }
    return false
  }

  async function rename(oldPath, newPath) {
    if (isElectron()) {
      return window.electronAPI.fs.rename(oldPath, newPath)
    }
    return null
  }

  function watch(watchPath, callback) {
    if (isElectron()) {
      window.electronAPI.fs.watch(watchPath)
      window.electronAPI.fs.onChange(callback)
    }
  }

  return { loading, listFiles, readFile, writeFile, deleteFile, stat, mkdir, exists, rename, watch }
}
