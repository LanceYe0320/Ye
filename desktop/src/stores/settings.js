import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiFetch } from '../lib/api.js'

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref({
    model: 'glm-4-plus',
    temperature: 0.7,
    max_tokens: 4096,
    theme: 'dark',
    terminal_allowlist: [],
  })
  const wsConnected = ref(false)

  async function fetchSettings() {
    const res = await apiFetch('/api/settings/')
    settings.value = await res.json().then((d) => d.settings)
  }

  async function updateSettings(newSettings) {
    const res = await apiFetch('/api/settings/', {
      method: 'PUT',
      body: JSON.stringify({ settings: newSettings }),
    })
    const data = await res.json()
    settings.value = data.settings
  }

  return { settings, wsConnected, fetchSettings, updateSettings }
})
