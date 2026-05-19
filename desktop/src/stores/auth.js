import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiFetch, setToken, clearToken, getToken } from '../lib/api.js'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const token = ref(getToken())
  const isAuthenticated = computed(() => !!token.value)
  const loading = ref(false)
  const error = ref('')

  async function _authRequest(endpoint, username, password) {
    loading.value = true
    error.value = ''
    try {
      const res = await apiFetch(`/api/auth/${endpoint}`, {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || `${endpoint} failed`)
      token.value = data.access_token
      setToken(data.access_token)
      user.value = { id: data.user_id, username: data.username }
    } catch (e) {
      error.value = e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function login(username, password) {
    return _authRequest('login', username, password)
  }

  async function register(username, password) {
    return _authRequest('register', username, password)
  }

  function logout() {
    token.value = null
    user.value = null
    clearToken()
  }

  return { user, token, isAuthenticated, loading, error, login, register, logout }
})
