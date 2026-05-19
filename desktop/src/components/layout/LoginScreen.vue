<template>
  <div class="login-screen">
    <div class="login-card">
      <div class="logo">{{ isRegister ? 'Create Account' : 'Sign In' }}</div>
      <form @submit.prevent="handleSubmit" class="login-form">
        <input
          v-model="username"
          type="text"
          placeholder="Username"
          autocomplete="username"
          :disabled="authStore.loading"
        />
        <input
          v-model="password"
          type="password"
          placeholder="Password (6+ characters)"
          autocomplete="current-password"
          :disabled="authStore.loading"
        />
        <div v-if="authStore.error" class="error">{{ authStore.error }}</div>
        <button type="submit" :disabled="!canSubmit || authStore.loading">
          {{ authStore.loading ? '...' : (isRegister ? 'Register' : 'Login') }}
        </button>
      </form>
      <div class="switch-mode">
        <span v-if="isRegister">Already have an account?</span>
        <span v-else>Don't have an account?</span>
        <button class="link-btn" @click="isRegister = !isRegister">
          {{ isRegister ? 'Login' : 'Register' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useAuthStore } from '../../stores/auth.js'

const authStore = useAuthStore()
const username = ref('')
const password = ref('')
const isRegister = ref(false)

const canSubmit = computed(() => username.value.length >= 2 && password.value.length >= 6)

async function handleSubmit() {
  try {
    if (isRegister.value) {
      await authStore.register(username.value, password.value)
    } else {
      await authStore.login(username.value, password.value)
    }
  } catch {
    // error is already set in store
  }
}
</script>

<style scoped>
.login-screen {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  background: var(--bg-primary);
}
.login-card {
  width: 360px;
  padding: 32px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
}
.logo {
  font-size: 20px;
  font-weight: 700;
  text-align: center;
  margin-bottom: 24px;
  color: var(--text-primary);
}
.login-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
input {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-primary);
  padding: 10px 12px;
  font-size: 14px;
  outline: none;
}
input:focus {
  border-color: var(--accent);
}
input:disabled {
  opacity: 0.5;
}
.error {
  color: #F38BA8;
  font-size: 13px;
}
button[type="submit"] {
  background: var(--accent);
  color: var(--bg-primary);
  border: none;
  border-radius: 8px;
  padding: 10px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}
button[type="submit"]:disabled {
  opacity: 0.4;
  cursor: default;
}
.switch-mode {
  margin-top: 16px;
  text-align: center;
  font-size: 13px;
  color: var(--text-muted);
}
.link-btn {
  background: none;
  border: none;
  color: var(--accent);
  cursor: pointer;
  font-size: 13px;
  margin-left: 4px;
}
</style>
