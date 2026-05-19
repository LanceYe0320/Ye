import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiFetch } from '../lib/api.js'

export const useProjectStore = defineStore('project', () => {
  const projects = ref([])
  const currentProject = ref(null)
  const openFiles = ref([])
  const activeFile = ref(null)

  const currentProjectId = computed(() => currentProject.value?.id ?? null)

  async function fetchProjects() {
    try {
      const res = await apiFetch('/api/projects/')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      projects.value = await res.json()
    } catch (e) {
      console.error('Failed to fetch projects:', e)
    }
  }

  async function createProject(name, path) {
    try {
      const res = await apiFetch('/api/projects/', {
        method: 'POST',
        body: JSON.stringify({ name, path }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const project = await res.json()
      projects.value.push(project)
      currentProject.value = project
      return project
    } catch (e) {
      console.error('Failed to create project:', e)
      throw e
    }
  }

  function selectProject(project) {
    currentProject.value = project
    openFiles.value = []
    activeFile.value = null
  }

  function openFile(file) {
    if (!openFiles.value.find((f) => f.path === file.path)) {
      openFiles.value.push(file)
    }
    activeFile.value = file
  }

  function closeFile(path) {
    openFiles.value = openFiles.value.filter((f) => f.path !== path)
    if (activeFile.value?.path === path) {
      activeFile.value = openFiles.value[openFiles.value.length - 1] || null
    }
  }

  return {
    projects, currentProject, openFiles, activeFile, currentProjectId,
    fetchProjects, createProject, selectProject, openFile, closeFile,
  }
})
