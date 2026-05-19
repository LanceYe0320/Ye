<template>
  <div class="main-layout">
    <TitleBar />
    <div class="content-area">
      <Sidebar
        @open-project="handleOpenProject"
        @new-conversation="handleNewConversation"
        @toggle-view="toggleView"
      />
      <div class="center-panel">
        <div class="center-top">
          <FileTree v-if="projectStore.currentProject" />
          <div class="editor-area">
            <WelcomeScreen v-if="!projectStore.currentProject" @open-project="handleOpenProject" />
            <template v-else>
              <EditorTabs v-if="projectStore.openFiles.length > 0" />
              <div class="editor-content" v-if="projectStore.openFiles.length > 0">
                <MonacoEditor
                  v-if="projectStore.activeFile"
                  :model-value="activeFileContent"
                  :file-path="projectStore.activeFile.path"
                  :read-only="false"
                  @update:model-value="onFileEdit"
                  @save="saveFile"
                />
              </div>
              <div class="center-bottom" v-if="projectStore.currentProject">
                <div class="terminal-header" @click="terminalOpen = !terminalOpen">
                  <span>Terminal</span>
                  <span>{{ terminalOpen ? '▼' : '▲' }}</span>
                </div>
                <div class="terminal-panel" v-show="terminalOpen">
                  <XTermTerminal
                    v-if="terminalOpen"
                    :project-id="projectStore.currentProjectId"
                  />
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>
      <div class="chat-area" v-if="projectStore.currentProject">
        <ChatPanel />
      </div>
    </div>
    <StatusBar />
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'
import { useProjectStore } from '../../stores/project.js'
import { useConversationStore } from '../../stores/conversation.js'
import { apiFetch } from '../../lib/api.js'
import { syncService } from '../../lib/syncService.js'
import TitleBar from './TitleBar.vue'
import Sidebar from './Sidebar.vue'
import StatusBar from './StatusBar.vue'
import FileTree from '../file-explorer/FileTree.vue'
import ChatPanel from '../chat/ChatPanel.vue'
import WelcomeScreen from './WelcomeScreen.vue'
import EditorTabs from '../editor/EditorTabs.vue'
import MonacoEditor from '../editor/MonacoEditor.vue'
import XTermTerminal from '../terminal/XTermTerminal.vue'

const projectStore = useProjectStore()
const conversationStore = useConversationStore()
const terminalOpen = ref(true)

// --- File sync ---
let _fileSyncDocId = null
let _fileSyncCallback = null

function _unsubscribeFileSync() {
  if (_fileSyncDocId && _fileSyncCallback) {
    syncService.unsubscribe(_fileSyncDocId, _fileSyncCallback)
    _fileSyncDocId = null
    _fileSyncCallback = null
  }
}

onUnmounted(_unsubscribeFileSync)

projectStore.fetchProjects()
conversationStore.fetchConversations()

const activeFileContent = computed(() => projectStore.activeFile?.content ?? '')

watch(() => projectStore.activeFile, async (file) => {
  _unsubscribeFileSync()
  if (!file) return
  if (file.content === undefined) await loadFileContent(file)
  if (projectStore.currentProjectId) {
    _fileSyncDocId = `file:${projectStore.currentProjectId}:${file.path}`
    _fileSyncCallback = () => {
      if (projectStore.activeFile?.path === file.path) loadFileContent(projectStore.activeFile)
    }
    syncService.subscribe(_fileSyncDocId, _fileSyncCallback)
  }
})

async function loadFileContent(file) {
  try {
    const projectId = projectStore.currentProjectId
    const res = await apiFetch(`/api/projects/${projectId}/files/${encodeURIComponent(file.path)}`)
    if (!res.ok) return
    const data = await res.json()
    file.content = data.content ?? ''
    file.originalContent = file.content
  } catch (e) {
    console.error('Failed to load file:', e)
  }
}

function onFileEdit(newContent) {
  if (projectStore.activeFile) {
    projectStore.activeFile.content = newContent
    projectStore.activeFile.modified = newContent !== projectStore.activeFile.originalContent
  }
}

async function saveFile(content) {
  if (!projectStore.activeFile) return
  const projectId = projectStore.currentProjectId
  const path = projectStore.activeFile.path
  try {
    const res = await apiFetch(`/api/projects/${projectId}/files/${encodeURIComponent(path)}`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    })
    if (res.ok) {
      projectStore.activeFile.originalContent = content
      projectStore.activeFile.modified = false
      if (_fileSyncDocId) {
        syncService.sendUpdate(_fileSyncDocId, { updated_at: Date.now() })
      }
    }
  } catch (e) {
    console.error('Save failed:', e)
  }
}

async function handleOpenProject() {
  const path = prompt('Enter the project directory path:')
  if (!path) return
  const name = path.split(/[/\\]/).pop()
  await projectStore.createProject(name, path)
}

async function handleNewConversation() {
  await conversationStore.createConversation('New Conversation', projectStore.currentProjectId)
}

function toggleView(view) {
  if (view === 'terminal') terminalOpen.value = !terminalOpen.value
}
</script>

<style scoped>
.main-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg-primary);
}
.content-area {
  display: flex;
  flex: 1;
  overflow: hidden;
}
.center-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}
.center-top {
  flex: 1;
  display: flex;
  overflow: hidden;
}
.editor-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}
.editor-content {
  flex: 1;
  overflow: hidden;
}
.center-bottom {
  flex-shrink: 0;
  border-top: 1px solid var(--border-primary);
}
.terminal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 12px;
  background: var(--bg-secondary);
  cursor: pointer;
  font-size: 12px;
  color: var(--text-secondary);
  user-select: none;
}
.terminal-header:hover {
  background: var(--bg-hover);
}
.terminal-panel {
  height: 220px;
  overflow: hidden;
}
.chat-area {
  width: 380px;
  flex-shrink: 0;
  border-left: 1px solid var(--border-primary);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
</style>
