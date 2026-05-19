import { ref } from 'vue'

const isElectron = () => !!window.electronAPI?.git

export function useGit(projectId) {
  const status = ref(null)
  const log = ref([])
  const branches = ref([])
  const isLoading = ref(false)

  function getProjectId() {
    return projectId.value ?? projectId
  }

  // Resolve repo path — in Electron the git service operates on absolute paths,
  // but we store the project root path from the project store or pass it through.
  // For HTTP fallback we use the project ID.

  let _repoPath = null

  function setRepoPath(path) {
    _repoPath = path
  }

  // --- Status ---

  async function fetchStatus() {
    isLoading.value = true
    try {
      if (isElectron() && _repoPath) {
        status.value = await window.electronAPI.git.status(_repoPath)
      } else {
        const res = await fetch(`/api/projects/${getProjectId()}/git/status`)
        status.value = await res.json()
      }
    } catch (e) {
      console.error('Git status failed:', e)
    } finally {
      isLoading.value = false
    }
  }

  // --- Log ---

  async function fetchLog(count = 20) {
    isLoading.value = true
    try {
      if (isElectron() && _repoPath) {
        log.value = await window.electronAPI.git.log(_repoPath, count)
      } else {
        const res = await fetch(`/api/projects/${getProjectId()}/git/log?count=${count}`)
        log.value = await res.json()
      }
    } catch (e) {
      console.error('Git log failed:', e)
    } finally {
      isLoading.value = false
    }
  }

  // --- Branches ---

  async function fetchBranches() {
    try {
      if (isElectron() && _repoPath) {
        branches.value = await window.electronAPI.git.branches(_repoPath)
      } else {
        const res = await fetch(`/api/projects/${getProjectId()}/git/branches`)
        branches.value = await res.json()
      }
    } catch (e) {
      console.error('Git branches failed:', e)
    }
  }

  // --- Diff ---

  async function getDiff({ staged = false, file } = {}) {
    if (isElectron() && _repoPath) {
      return window.electronAPI.git.diff(_repoPath, { staged, file })
    }
    let url = `/api/projects/${getProjectId()}/git/diff?`
    if (staged) url += 'staged=true'
    if (file) url += `&file=${encodeURIComponent(file)}`
    const res = await fetch(url)
    const data = await res.json()
    return data.diff
  }

  // --- Commit ---

  async function commit(message, files) {
    if (isElectron() && _repoPath) {
      return window.electronAPI.git.commit(_repoPath, { message, files })
    }
    const res = await fetch(`/api/projects/${getProjectId()}/git/commit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, files }),
    })
    return res.json()
  }

  // --- AI Commit ---

  async function aiCommit() {
    const res = await fetch(`/api/projects/${getProjectId()}/git/commit-ai`, {
      method: 'POST',
    })
    return res.json()
  }

  // --- Checkout ---

  async function checkout(branch, create = false) {
    if (isElectron() && _repoPath) {
      return window.electronAPI.git.checkout(_repoPath, { branch, create })
    }
    const res = await fetch(`/api/projects/${getProjectId()}/git/checkout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ branch, create }),
    })
    return res.json()
  }

  // --- Review ---

  async function review() {
    const res = await fetch(`/api/projects/${getProjectId()}/git/review`, {
      method: 'POST',
    })
    return res.json()
  }

  return {
    status, log, branches, isLoading,
    fetchStatus, fetchLog, fetchBranches,
    getDiff, commit, aiCommit, checkout, review,
    setRepoPath,
  }
}
