<template>
  <div class="welcome">
    <div class="welcome-content">
      <h1>AI Coding Assistant</h1>
      <p class="subtitle">Powered by Zhipu GLM-4</p>
      <div class="actions">
        <button class="btn-primary" @click="$emit('open-project')">Open Project</button>
        <p class="hint">Select a project directory to get started</p>
      </div>
      <div class="features">
        <div class="feature">
          <span class="feature-icon">&#128172;</span>
          <span>AI Chat</span>
        </div>
        <div class="feature">
          <span class="feature-icon">&#128196;</span>
          <span>File Operations</span>
        </div>
        <div class="feature">
          <span class="feature-icon">&#128187;</span>
          <span>Terminal</span>
        </div>
        <div class="feature">
          <span class="feature-icon">&#128270;</span>
          <span>Code Search</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineEmits(['open-project'])
</script>

<style scoped>
.welcome {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.welcome-content {
  text-align: center;
  max-width: 500px;
}
h1 {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 8px;
}
.subtitle {
  color: var(--text-muted);
  margin-bottom: 32px;
}
.btn-primary {
  padding: 10px 24px;
  background: var(--accent);
  color: var(--bg-tertiary);
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}
.btn-primary:hover {
  background: var(--accent-hover);
}
.hint {
  color: var(--text-muted);
  font-size: 12px;
  margin-top: 12px;
}
.features {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
  margin-top: 40px;
}
.feature {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}
.feature-icon {
  font-size: 18px;
}
</style>
