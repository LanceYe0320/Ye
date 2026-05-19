<template>
  <LoginScreen v-if="!authStore.isAuthenticated" />
  <MainLayout v-else />
</template>

<script setup>
import { useAuthStore } from './stores/auth.js'
import LoginScreen from './components/layout/LoginScreen.vue'
import MainLayout from './components/layout/MainLayout.vue'

const authStore = useAuthStore()
</script>
