// Shared type definitions for backend ↔ frontend communication

// ─── Projects ───

export interface Project {
  id: number
  name: string
  path: string
  user_id: number
  created_at: string
}

// ─── Files ───

export interface DirEntry {
  name: string
  path: string
  is_dir: boolean
  size: number
}

export interface FileContent {
  path: string
  content: string
}

export interface FileWrite {
  content: string
}

// ─── Conversations ───

export interface Conversation {
  id: number
  title: string
  model: string
  project_id: number | null
  user_id: number
  created_at: string
  updated_at: string
}

export type MessageRole = 'user' | 'assistant' | 'tool' | 'system'

export interface Message {
  id: number
  conversation_id: number
  role: MessageRole
  content: string
  tool_calls_json: string | null
  tool_call_id: string | null
  token_usage_json: string | null
  created_at: string
}

// ─── LLM ───

export interface ToolCall {
  id: string
  name: string
  arguments: string
}

export interface StreamingChunk {
  type: 'text_delta' | 'tool_call_start' | 'tool_call_end' | 'tool_execution_start' | 'tool_execution_result' | 'done' | 'error'
  text?: string
  tool_call_id?: string
  tool_call_name?: string
  tool_call_arguments?: string
  usage?: Record<string, number>
}

// ─── Git ───

export interface GitStatus {
  branch: string
  staged: string[]
  unstaged: string[]
  untracked: string[]
}

export interface GitCommit {
  hash: string
  author: string
  date: string
  message: string
}

export interface GitBranch {
  name: string
  active: boolean
}

// ─── Search ───

export interface SearchResult {
  id: string
  content: string
  metadata: Record<string, unknown>
  distance: number | null
}

// ─── Auth ───

export interface AuthResponse {
  access_token: string
  token_type: 'bearer'
  user_id: number
  username: string
}

// ─── Plugins ───

export interface PluginInfo {
  name: string
  version: string
  description: string
  tools: string[]
}

// ─── WebSocket Messages ───

export interface WsChatMessage {
  content: string
  model?: string
}

export interface WsTerminalMessage {
  command: string
}

export interface WsSyncSubscribe {
  type: 'subscribe'
  doc_id: string
}

export interface WsSyncUpdate {
  type: 'sync_update'
  doc_id: string
  update: Record<string, unknown>
}

export interface WsSyncFull {
  type: 'sync_full'
  doc_id: string
  state: Record<string, unknown>
  version: number
}

// ─── Settings ───

export interface UserSettings {
  model: string
  temperature: number
  max_tokens: number
  theme: 'dark' | 'light'
  font_size: number
  command_timeout: number
}
