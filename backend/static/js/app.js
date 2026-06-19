/**
 * CodeAI Frontend - SPA Application
 * A modern AI coding assistant web interface
 */
const App = {
  state: {
    token: localStorage.getItem('token') || '',
    user: null,
    projects: [],
    currentProject: null,
    conversations: [],
    currentConversation: null,
    messages: [],
    files: [],
    currentFile: null,
    openTabs: [],
    terminalHistory: [],
    settings: {},
    ws: null,
    loading: false,
  },

  init() {
    const root = document.getElementById('app');
    if (this.state.token) {
      this.fetchUser().then(() => this.renderApp()).catch(() => {
        this.state.token = '';
        localStorage.removeItem('token');
        this.renderAuth();
      });
    } else {
      this.renderAuth();
    }
  },

  api(method, path, body = null) {
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (this.state.token) opts.headers['Authorization'] = `Bearer ${this.state.token}`;
    if (body) opts.body = JSON.stringify(body);
    return fetch(path, opts).then(async r => {
      if (r.status === 401) {
        this.state.token = '';
        localStorage.removeItem('token');
        this.renderAuth();
        throw new Error('Unauthorized');
      }
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || 'Request failed');
      return data;
    });
  },

  async fetchUser() {
    this.state.user = await this.api('GET', '/api/auth/me');
  },

  // ===== AUTH =====
  renderAuth() {
    const isLogin = true;
    document.getElementById('app').innerHTML = `
      <div class="auth-overlay">
        <div class="auth-card">
          <h1>⚡ CodeAI</h1>
          <p class="subtitle">AI 驱动的智能编程助手</p>
          <div class="auth-error" id="authError"></div>
          <form id="authForm">
            <div class="form-group" id="nameGroup" style="display:none">
              <label>用户名</label>
              <input type="text" id="authName" placeholder="输入用户名" autocomplete="username">
            </div>
            <div class="form-group">
              <label>邮箱</label>
              <input type="email" id="authEmail" placeholder="your@email.com" autocomplete="email">
            </div>
            <div class="form-group">
              <label>密码</label>
              <input type="password" id="authPassword" placeholder="输入密码" autocomplete="current-password">
            </div>
            <button type="submit" class="btn-primary" id="authSubmit">登录</button>
          </form>
          <div class="switch-mode">
            <span id="switchText">还没有账号？</span>
            <a href="#" id="switchLink">注册</a>
          </div>
        </div>
      </div>`;

    let loginMode = true;
    document.getElementById('switchLink').onclick = (e) => {
      e.preventDefault();
      loginMode = !loginMode;
      document.getElementById('nameGroup').style.display = loginMode ? 'none' : 'block';
      document.getElementById('authSubmit').textContent = loginMode ? '登录' : '注册';
      document.getElementById('switchText').textContent = loginMode ? '还没有账号？' : '已有账号？';
      document.getElementById('switchLink').textContent = loginMode ? '注册' : '登录';
      document.getElementById('authError').style.display = 'none';
    };

    document.getElementById('authForm').onsubmit = async (e) => {
      e.preventDefault();
      const errEl = document.getElementById('authError');
      errEl.style.display = 'none';
      try {
        const email = document.getElementById('authEmail').value;
        const password = document.getElementById('authPassword').value;
        if (loginMode) {
          const data = await this.api('POST', '/api/auth/login', { email, password });
          this.state.token = data.access_token;
          localStorage.setItem('token', data.access_token);
        } else {
          const name = document.getElementById('authName').value;
          await this.api('POST', '/api/auth/register', { email, password, name });
          const data = await this.api('POST', '/api/auth/login', { email, password });
          this.state.token = data.access_token;
          localStorage.setItem('token', data.access_token);
        }
        await this.fetchUser();
        this.renderApp();
      } catch (err) {
        errEl.textContent = err.message;
        errEl.style.display = 'block';
      }
    };
  },

  // ===== MAIN APP =====
  renderApp() {
    const user = this.state.user || {};
    const initial = (user.name || user.email || 'U')[0].toUpperCase();
    document.getElementById('app').innerHTML = `
      <div class="app-layout">
        <aside class="sidebar">
          <div class="sidebar-header">
            <span class="logo">⚡ CodeAI</span>
            <button class="btn-icon" title="新建对话" onclick="App.newChat()">✚</button>
          </div>
          <nav class="sidebar-nav" id="sidebarNav">
            <div class="nav-section">
              <div class="nav-section-title">项目</div>
              <div id="projectList"></div>
              <button class="nav-item" onclick="App.showNewProjectModal()">
                <span class="icon">📁</span> 新建项目...
              </button>
            </div>
            <div class="nav-section">
              <div class="nav-section-title">对话</div>
              <div id="conversationList"><div style="padding:8px 10px;font-size:12px;color:var(--text-muted)">选择项目后查看对话</div></div>
            </div>
          </nav>
          <div class="sidebar-footer">
            <div class="avatar">${initial}</div>
            <div class="user-info">
              <div class="user-name">${user.name || user.email || 'User'}</div>
              <div class="user-plan">Free Plan</div>
            </div>
            <button class="btn-icon" title="设置" onclick="App.showSettings()">⚙️</button>
            <button class="btn-icon" title="退出" onclick="App.logout()">🚪</button>
          </div>
        </aside>
        <div class="main-content" id="mainContent">
          <div class="chat-welcome" id="welcomeScreen">
            <h2>欢迎使用 CodeAI</h2>
            <p>你的 AI 编程助手。选择或创建一个项目，开始智能编程之旅。</p>
            <div class="quick-actions">
              <div class="quick-action" onclick="App.showNewProjectModal()">
                <div class="qa-icon">📂</div>
                <div class="qa-title">新建项目</div>
                <div class="qa-desc">创建一个新的编程项目</div>
              </div>
              <div class="quick-action" onclick="App.quickPrompt('帮我写一个 Python Web 服务器')">
                <div class="qa-icon">💻</div>
                <div class="qa-title">代码生成</div>
                <div class="qa-desc">AI 帮你快速生成代码</div>
              </div>
              <div class="quick-action" onclick="App.quickPrompt('解释一下这段代码的工作原理')">
                <div class="qa-icon">🔍</div>
                <div class="qa-title">代码解读</div>
                <div class="qa-desc">深入理解代码逻辑</div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="modal-overlay" id="modalOverlay" style="display:none"></div>
      <div class="toast-container" id="toastContainer"></div>`;
    this.loadProjects();
  },

  logout() {
    this.state.token = '';
    this.state.user = null;
    localStorage.removeItem('token');
    if (this.state.ws) { this.state.ws.close(); this.state.ws = null; }
    this.renderAuth();
  },

  // ===== PROJECTS =====
  async loadProjects() {
    try {
      this.state.projects = await this.api('GET', '/api/projects/');
      this.renderProjectList();
    } catch (e) { console.error(e); }
  },

  renderProjectList() {
    const list = document.getElementById('projectList');
    if (!list) return;
    if (this.state.projects.length === 0) {
      list.innerHTML = '<div style="padding:8px 10px;font-size:12px;color:var(--text-muted)">暂无项目</div>';
      return;
    }
    list.innerHTML = this.state.projects.map(p => `
      <button class="nav-item ${this.state.currentProject?.id === p.id ? 'active' : ''}" onclick="App.selectProject(${p.id})">
        <span class="icon">📁</span> ${this.escapeHtml(p.name)}
      </button>`).join('');
  },

  async selectProject(id) {
    try {
      const project = this.state.projects.find(p => p.id === id);
      this.state.currentProject = project;
      this.renderProjectList();
      this.loadConversations(id);
      this.loadFiles(id);
      this.renderProjectView();
    } catch (e) { this.toast('加载项目失败', 'error'); }
  },

  showNewProjectModal() {
    const overlay = document.getElementById('modalOverlay');
    overlay.style.display = 'flex';
    overlay.innerHTML = `
      <div class="modal">
        <h3>📁 新建项目</h3>
        <div class="form-group">
          <label>项目名称</label>
          <input type="text" id="projName" placeholder="my-awesome-project">
        </div>
        <div class="form-group">
          <label>项目路径</label>
          <input type="text" id="projPath" placeholder="/path/to/project">
        </div>
        <div class="form-group">
          <label>描述（可选）</label>
          <input type="text" id="projDesc" placeholder="项目描述...">
        </div>
        <div class="modal-actions">
          <button class="btn btn-secondary" onclick="App.closeModal()">取消</button>
          <button class="btn btn-accent" onclick="App.createProject()">创建</button>
        </div>
      </div>`;
  },

  async createProject() {
    const name = document.getElementById('projName').value.trim();
    const path = document.getElementById('projPath').value.trim();
    const desc = document.getElementById('projDesc').value.trim();
    if (!name) { this.toast('请输入项目名称', 'error'); return; }
    try {
      await this.api('POST', '/api/projects/', { name, path, description: desc });
      this.closeModal();
      this.toast('项目创建成功！', 'success');
      this.loadProjects();
    } catch (e) { this.toast(e.message, 'error'); }
  },

  closeModal() {
    document.getElementById('modalOverlay').style.display = 'none';
  },

  // ===== CONVERSATIONS =====
  async loadConversations(projectId) {
    try {
      this.state.conversations = await this.api('GET', `/api/projects/${projectId}/conversations/`);
      this.renderConversationList();
    } catch (e) { console.error(e); }
  },

  renderConversationList() {
    const list = document.getElementById('conversationList');
    if (!list) return;
    if (!this.state.currentProject) {
      list.innerHTML = '<div style="padding:8px 10px;font-size:12px;color:var(--text-muted)">选择项目后查看对话</div>';
      return;
    }
    if (this.state.conversations.length === 0) {
      list.innerHTML = '<div style="padding:8px 10px;font-size:12px;color:var(--text-muted)">暂无对话</div>';
      return;
    }
    list.innerHTML = this.state.conversations.map(c => `
      <button class="nav-item ${this.state.currentConversation?.id === c.id ? 'active' : ''}" onclick="App.selectConversation(${c.id})">
        <span class="icon">💬</span>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${this.escapeHtml(c.title || '新对话')}</span>
      </button>`).join('');
  },

  async selectConversation(id) {
    try {
      const conv = this.state.conversations.find(c => c.id === id);
      this.state.currentConversation = conv;
      this.renderConversationList();
      this.state.messages = await this.api('GET', `/api/projects/${this.state.currentProject.id}/conversations/${id}/messages/`);
      this.renderProjectView();
      this.renderMessages();
    } catch (e) { this.toast('加载对话失败', 'error'); }
  },

  async newChat() {
    if (!this.state.currentProject) {
      this.toast('请先选择一个项目', 'info');
      return;
    }
    try {
      const conv = await this.api('POST', `/api/projects/${this.state.currentProject.id}/conversations/`, {
        title: '新对话',
      });
      this.state.currentConversation = conv;
      this.state.messages = [];
      this.loadConversations(this.state.currentProject.id);
      this.renderProjectView();
      this.toast('新对话已创建', 'success');
    } catch (e) { this.toast(e.message, 'error'); }
  },

  // ===== PROJECT VIEW =====
  renderProjectView() {
    const main = document.getElementById('mainContent');
    if (!this.state.currentProject) return;
    const proj = this.state.currentProject;
    main.innerHTML = `
      <div class="main-header">
        <div class="header-left">
          <span style="font-size:16px">📁</span>
          <span class="header-title">${this.escapeHtml(proj.name)}</span>
          ${this.state.currentConversation ? `<span style="color:var(--text-muted)">/ ${this.escapeHtml(this.state.currentConversation.title || '对话')}</span>` : ''}
        </div>
        <div class="header-right">
          <button class="btn btn-secondary btn-icon" title="文件浏览器" onclick="App.toggleFiles()">📂</button>
          <button class="btn btn-secondary btn-icon" title="终端" onclick="App.toggleTerminal()">💻</button>
          <button class="btn btn-accent" onclick="App.newChat()">✚ 新对话</button>
        </div>
      </div>
      <div class="split-layout" style="flex:1;overflow:hidden;flex-direction:column">
        <div class="chat-area" style="flex:1;display:flex;flex-direction:column">
          <div class="chat-messages" id="chatMessages"></div>
          <div class="chat-input-area">
            <div class="chat-input-wrapper">
              <textarea id="chatInput" rows="1" placeholder="输入消息，按 Enter 发送，Shift+Enter 换行..."
                oninput="App.autoResize(this)" onkeydown="App.handleInputKey(event)"></textarea>
              <div class="chat-input-actions">
                <div class="left-actions">
                  <button class="btn-icon" title="上传文件" style="font-size:14px">📎</button>
                </div>
                <button class="send-btn" id="sendBtn" onclick="App.sendMessage()" title="发送">
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M1 8l14-6-6 14v-6H1z"/></svg>
                </button>
              </div>
            </div>
            <div class="chat-hint">Enter 发送 · Shift+Enter 换行 · 支持自然语言描述编程需求</div>
          </div>
        </div>
        <div class="terminal-area" id="terminalArea" style="display:none">
          <div class="terminal-header">
            <span>💻 终端 — ${this.escapeHtml(proj.name)}</span>
            <button class="btn-icon" onclick="App.toggleTerminal()" style="font-size:14px">✕</button>
          </div>
          <div class="terminal-body" id="terminalBody"></div>
          <div class="terminal-input-line">
            <span class="prompt">$</span>
            <input id="terminalInput" placeholder="输入命令..." onkeydown="if(event.key==='Enter')App.execCommand()">
          </div>
        </div>
      </div>`;
    this.renderMessages();
    this.connectWS();
  },

  // ===== MESSAGES =====
  renderMessages() {
    const container = document.getElementById('chatMessages');
    if (!container) return;
    if (!this.state.messages || this.state.messages.length === 0) {
      container.innerHTML = `
        <div class="chat-welcome">
          <h2 style="font-size:24px">开始对话</h2>
          <p style="max-width:400px">向 AI 助手描述你的编程需求，它会帮你编写、分析和优化代码。</p>
        </div>`;
      return;
    }
    container.innerHTML = this.state.messages.map(m => this.renderMessage(m)).join('');
    container.scrollTop = container.scrollHeight;
  },

  renderMessage(msg) {
    const isUser = msg.role === 'user';
    const time = msg.created_at ? new Date(msg.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '';
    const avatar = isUser ? '👤' : '⚡';
    const sender = isUser ? (this.state.user?.name || '你') : 'CodeAI';
    const content = this.formatContent(msg.content || '');
    return `
      <div class="message ${msg.role}">
        <div class="message-avatar">${avatar}</div>
        <div class="message-body">
          <div class="message-header">
            <span class="message-sender">${this.escapeHtml(sender)}</span>
            <span class="message-time">${time}</span>
          </div>
          <div class="message-content">${content}</div>
        </div>
      </div>`;
  },

  formatContent(text) {
    if (!text) return '';
    // Code blocks
    text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
      return `<pre><code class="language-${lang}">${this.escapeHtml(code.trim())}</code><button class="copy-btn" onclick="App.copyCode(this)">复制</button></pre>`;
    });
    // Inline code
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Bold
    text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Italic
    text = text.replace(/\*(.+?)\*/g, '<em>$1</em>');
    // Line breaks
    text = text.replace(/\n/g, '<br>');
    return text;
  },

  copyCode(btn) {
    const code = btn.parentElement.querySelector('code').textContent;
    navigator.clipboard.writeText(code).then(() => {
      btn.textContent = '已复制!';
      setTimeout(() => btn.textContent = '复制', 1500);
    });
  },

  // ===== CHAT INPUT & SEND =====
  autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  },

  handleInputKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      this.sendMessage();
    }
  },

  async sendMessage() {
    const input = document.getElementById('chatInput');
    if (!input) return;
    const text = input.value.trim();
    if (!text) return;

    if (!this.state.currentConversation) {
      await this.newChat();
    }

    // Add user message to UI
    const userMsg = { role: 'user', content: text, created_at: new Date().toISOString() };
    this.state.messages.push(userMsg);
    this.renderMessages();
    input.value = '';
    input.style.height = 'auto';

    // Show typing indicator
    this.appendTypingIndicator();

    // Send via WebSocket
    if (this.state.ws && this.state.ws.readyState === WebSocket.OPEN) {
      this.state.ws.send(JSON.stringify({
        type: 'chat',
        conversation_id: this.state.currentConversation?.id,
        project_id: this.state.currentProject?.id,
        message: text,
      }));
    } else {
      // Fallback: try REST API
      try {
        await this.api('POST', `/api/projects/${this.state.currentProject.id}/conversations/${this.state.currentConversation.id}/messages/`, {
          role: 'user',
          content: text,
        });
        this.removeTypingIndicator();
        this.toast('WebSocket 未连接，消息已保存', 'info');
      } catch (e) {
        this.removeTypingIndicator();
        this.toast('发送失败: ' + e.message, 'error');
      }
    }
  },

  quickPrompt(text) {
    if (!this.state.currentProject) {
      this.toast('请先选择或创建一个项目', 'info');
      return;
    }
    this.renderProjectView();
    setTimeout(() => {
      const input = document.getElementById('chatInput');
      if (input) { input.value = text; input.focus(); }
    }, 100);
  },

  appendTypingIndicator() {
    const container = document.getElementById('chatMessages');
    if (!container) return;
    const typing = document.createElement('div');
    typing.id = 'typingIndicator';
    typing.className = 'message assistant';
    typing.innerHTML = `
      <div class="message-avatar">⚡</div>
      <div class="message-body">
        <div class="typing-indicator"><span></span><span></span><span></span></div>
      </div>`;
    container.appendChild(typing);
    container.scrollTop = container.scrollHeight;
  },

  removeTypingIndicator() {
    const el = document.getElementById('typingIndicator');
    if (el) el.remove();
  },

  // ===== WEBSOCKET =====
  connectWS() {
    if (this.state.ws && this.state.ws.readyState === WebSocket.OPEN) return;
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${protocol}://${location.host}/ws/chat?token=${this.state.token}`;
    try {
      const ws = new WebSocket(url);
      this.state.ws = ws;
      ws.onopen = () => console.log('WebSocket connected');
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.handleWSMessage(data);
        } catch (e) { console.error('WS parse error', e); }
      };
      ws.onclose = () => {
        console.log('WebSocket closed');
        this.state.ws = null;
      };
      ws.onerror = (err) => {
        console.error('WebSocket error', err);
        this.state.ws = null;
      };
    } catch (e) { console.error('WS connect error', e); }
  },

  handleWSMessage(data) {
    if (data.type === 'stream_chunk') {
      // Streaming text chunk from AI
      this.removeTypingIndicator();
      let lastMsg = this.state.messages[this.state.messages.length - 1];
      if (!lastMsg || lastMsg.role !== 'assistant' || lastMsg._streaming !== true) {
        lastMsg = { role: 'assistant', content: '', created_at: new Date().toISOString(), _streaming: true };
        this.state.messages.push(lastMsg);
      }
      lastMsg.content += data.content || '';
      this.renderMessages();
    } else if (data.type === 'stream_end') {
      const lastMsg = this.state.messages[this.state.messages.length - 1];
      if (lastMsg) lastMsg._streaming = false;
      this.removeTypingIndicator();
      this.renderMessages();
    } else if (data.type === 'assistant_message') {
      this.removeTypingIndicator();
      this.state.messages.push({
        role: 'assistant',
        content: data.content,
        created_at: new Date().toISOString(),
      });
      this.renderMessages();
    } else if (data.type === 'tool_call') {
      this.removeTypingIndicator();
      this.state.messages.push({
        role: 'assistant',
        content: `🔧 **工具调用**: \`${data.tool_name}\`\n\`\`\`\n${data.args || ''}\n\`\`\``,
        created_at: new Date().toISOString(),
      });
      this.renderMessages();
    } else if (data.type === 'error') {
      this.removeTypingIndicator();
      this.toast(data.message || 'AI 响应出错', 'error');
    }
  },

  // ===== FILES =====
  async loadFiles(projectId) {
    try {
      this.state.files = await this.api('GET', `/api/projects/${projectId}/files/`);
    } catch (e) { console.error(e); }
  },

  toggleFiles() {
    let panel = document.getElementById('filesPanel');
    if (panel) { panel.remove(); return; }
    // Insert file panel into split layout
    const chatArea = document.querySelector('.chat-area');
    if (!chatArea) return;
    const wrapper = document.createElement('div');
    wrapper.id = 'filesPanel';
    wrapper.className = 'split-left';
    wrapper.innerHTML = `
      <div class="file-explorer">
        <div class="file-toolbar">
          <input type="text" placeholder="搜索文件..." oninput="App.filterFiles(this.value)">
          <button class="btn-icon" title="刷新" onclick="App.loadFiles(${this.state.currentProject.id})" style="font-size:14px">🔄</button>
        </div>
        <div class="file-tree" id="fileTree">${this.renderFileTree()}</div>
      </div>`;
    chatArea.parentElement.insertBefore(wrapper, chatArea);
  },

  renderFileTree() {
    if (!this.state.files || this.state.files.length === 0) {
      return '<div style="padding:12px;font-size:12px;color:var(--text-muted)">无文件</div>';
    }
    return this.state.files.map(f => {
      const icon = f.type === 'directory' ? '📁' : this.getFileIcon(f.name);
      return `<div class="file-item" onclick="App.openFile('${this.escapeAttr(f.path)}', '${f.type}')">
        <span class="file-icon">${icon}</span>
        <span class="file-name">${this.escapeHtml(f.name)}</span>
      </div>`;
    }).join('');
  },

  getFileIcon(name) {
    const ext = name.split('.').pop().toLowerCase();
    const icons = {
      js: '📜', ts: '📘', py: '🐍', html: '🌐', css: '🎨', json: '📋',
      md: '📝', txt: '📄', yml: '⚙️', yaml: '⚙️', toml: '⚙️', rs: '🦀',
      go: '🐹', java: '☕', cpp: '⚡', c: '⚡', h: '📎', sh: '🐚',
    };
    return icons[ext] || '📄';
  },

  filterFiles(query) {
    // Simple filter
    const items = document.querySelectorAll('#fileTree .file-item');
    items.forEach(item => {
      const name = item.querySelector('.file-name').textContent.toLowerCase();
      item.style.display = name.includes(query.toLowerCase()) ? '' : 'none';
    });
  },

  async openFile(path, type) {
    if (type === 'directory') return;
    try {
      const pid = this.state.currentProject.id;
      const content = await this.api('GET', `/api/projects/${pid}/files/content?path=${encodeURIComponent(path)}`);
      this.state.currentFile = { path, content: content.content || content };
      // Open in a simple modal viewer for now
      this.showFileViewer(path, this.state.currentFile.content);
    } catch (e) { this.toast('无法打开文件: ' + e.message, 'error'); }
  },

  showFileViewer(path, content) {
    const overlay = document.getElementById('modalOverlay');
    overlay.style.display = 'flex';
    overlay.innerHTML = `
      <div class="modal" style="width:700px;max-height:80vh;display:flex;flex-direction:column">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
          <h3 style="margin:0">📄 ${this.escapeHtml(path)}</h3>
          <button class="btn-icon" onclick="App.closeModal()">✕</button>
        </div>
        <pre style="flex:1;overflow:auto;background:var(--bg-primary);border:1px solid var(--border);border-radius:8px;padding:14px;font-family:var(--font-mono);font-size:13px;line-height:1.6;max-height:55vh;margin:0">${this.escapeHtml(content)}</pre>
      </div>`;
  },

  // ===== TERMINAL =====
  toggleTerminal() {
    const term = document.getElementById('terminalArea');
    if (!term) return;
    term.style.display = term.style.display === 'none' ? 'flex' : 'none';
    if (term.style.display === 'flex') {
      const input = document.getElementById('terminalInput');
      if (input) input.focus();
    }
  },

  async execCommand() {
    const input = document.getElementById('terminalInput');
    if (!input) return;
    const cmd = input.value.trim();
    if (!cmd) return;
    input.value = '';

    const body = document.getElementById('terminalBody');
    body.innerHTML += `<div class="terminal-line info">$ ${this.escapeHtml(cmd)}</div>`;

    try {
      const pid = this.state.currentProject.id;
      const result = await this.api('POST', `/api/projects/${pid}/terminal/execute`, { command: cmd });
      const stdout = result.stdout || result.output || '';
      const stderr = result.stderr || '';
      const exitCode = result.exit_code ?? result.returncode ?? 0;
      if (stdout) body.innerHTML += `<div class="terminal-line">${this.escapeHtml(stdout)}</div>`;
      if (stderr) body.innerHTML += `<div class="terminal-line error">${this.escapeHtml(stderr)}</div>`;
      if (exitCode !== 0) body.innerHTML += `<div class="terminal-line error">Exit code: ${exitCode}</div>`;
    } catch (e) {
      body.innerHTML += `<div class="terminal-line error">Error: ${this.escapeHtml(e.message)}</div>`;
    }
    body.scrollTop = body.scrollHeight;
  },

  // ===== SETTINGS =====
  showSettings() {
    const main = document.getElementById('mainContent');
    main.innerHTML = `
      <div class="main-header">
        <div class="header-left">
          <button class="btn-icon" onclick="App.renderApp()">←</button>
          <span class="header-title">⚙️ 设置</span>
        </div>
      </div>
      <div class="settings-page">
        <h2>设置</h2>
        <div class="settings-section">
          <h3>通用</h3>
          <div class="setting-item">
            <div class="setting-label">
              <div class="label">主题</div>
              <div class="desc">选择界面主题</div>
            </div>
            <select class="setting-input">
              <option value="dark" selected>深色模式</option>
              <option value="light">浅色模式</option>
            </select>
          </div>
          <div class="setting-item">
            <div class="setting-label">
              <div class="label">字体大小</div>
              <div class="desc">代码编辑器字体大小</div>
            </div>
            <select class="setting-input">
              <option>12px</option><option>13px</option><option selected>14px</option><option>15px</option><option>16px</option>
            </select>
          </div>
        </div>
        <div class="settings-section">
          <h3>AI 助手</h3>
          <div class="setting-item">
            <div class="setting-label">
              <div class="label">模型</div>
              <div class="desc">选择 AI 模型</div>
            </div>
            <select class="setting-input">
              <option>glm-4</option><option>glm-4-flash</option><option>glm-3-turbo</option>
            </select>
          </div>
          <div class="setting-item">
            <div class="setting-label">
              <div class="label">流式输出</div>
              <div class="desc">实时显示 AI 响应</div>
            </div>
            <div class="toggle active" onclick="this.classList.toggle('active')"></div>
          </div>
          <div class="setting-item">
            <div class="setting-label">
              <div class="label">温度</div>
              <div class="desc">控制回答的随机性 (0-1)</div>
            </div>
            <input type="number" class="setting-input" value="0.7" min="0" max="1" step="0.1">
          </div>
        </div>
      </div>`;
  },

  // ===== UTILITIES =====
  toast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const icons = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' };
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${icons[type] || ''}</span><span>${this.escapeHtml(message)}</span>`;
    container.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; toast.style.transform = 'translateX(100%)'; toast.style.transition = 'all 0.3s'; setTimeout(() => toast.remove(), 300); }, 3500);
  },

  escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  },

  escapeAttr(str) {
    if (!str) return '';
    return str.replace(/'/g, "\\'").replace(/"/g, '&quot;');
  },
};

// Boot the app
document.addEventListener('DOMContentLoaded', () => App.init());
