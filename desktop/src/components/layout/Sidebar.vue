<template>
  <div class="sidebar">
    <div class="sidebar-icons">
      <button class="icon-btn" title="Files" @click="$emit('open-project')">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
        </svg>
      </button>
      <button class="icon-btn" title="Chat" @click="$emit('new-conversation')">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
      </button>
      <button class="icon-btn" title="Settings" @click="showSettings = !showSettings">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
        </svg>
      </button>
    </div>
    <div class="sidebar-bottom">
      <div class="avatar">U</div>
    </div>
  </div>
</template>

<script setup>
defineEmits(['open-project', 'new-conversation'])
</script>

<style scoped>
.sidebar {
  width: 48px;
  background: var(--bg-tertiary);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  border-right: 1px solid var(--border);
}
.sidebar-icons {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.icon-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 6px;
}
.icon-btn:hover {
  background: var(--border);
  color: var(--text-primary);
}
.sidebar-bottom {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--accent);
  color: var(--bg-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
}
</style>
