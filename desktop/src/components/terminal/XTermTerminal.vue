<template>
  <div ref="terminalContainer" class="xterm-terminal"></div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { Terminal } from 'xterm'
import { FitAddon } from 'xterm-addon-fit'
import { WebLinksAddon } from 'xterm-addon-web-links'
import 'xterm/css/xterm.css'

const props = defineProps({
  projectId: { type: Number, required: true },
})

const terminalContainer = ref(null)
let terminal = null
let fitAddon = null
let ws = null
let resizeObserver = null

onMounted(() => {
  terminal = new Terminal({
    theme: {
      background: '#1e1e2e',
      foreground: '#cdd6f4',
      cursor: '#f5e0dc',
      cursorAccent: '#1e1e2e',
      selectionBackground: '#585b7066',
      black: '#45475a',
      red: '#f38ba8',
      green: '#a6e3a1',
      yellow: '#f9e2af',
      blue: '#89b4fa',
      magenta: '#f5c2e7',
      cyan: '#94e2d5',
      white: '#bac2de',
      brightBlack: '#585b70',
      brightRed: '#f38ba8',
      brightGreen: '#a6e3a1',
      brightYellow: '#f9e2af',
      brightBlue: '#89b4fa',
      brightMagenta: '#f5c2e7',
      brightCyan: '#94e2d5',
      brightWhite: '#a6adc8',
    },
    fontSize: 14,
    fontFamily: '"Cascadia Code", "Fira Code", "JetBrains Mono", Consolas, monospace',
    cursorBlink: true,
    scrollback: 5000,
    convertEol: true,
  })

  fitAddon = new FitAddon()
  terminal.loadAddon(fitAddon)
  terminal.loadAddon(new WebLinksAddon())

  terminal.open(terminalContainer.value)
  fitAddon.fit()

  terminal.writeln('\x1b[1;36m~ AI Coding Assistant Terminal ~\x1b[0m')
  terminal.writeln('\x1b[90mType commands below. Output streams in real-time.\x1b[0m\r\n')

  connectWs()

  let currentLine = ''
  terminal.onData((data) => {
    if (data === '\r') {
      terminal.writeln('')
      if (currentLine.trim()) {
        sendCommand(currentLine.trim())
      }
      currentLine = ''
    } else if (data === '\x7f') {
      if (currentLine.length > 0) {
        currentLine = currentLine.slice(0, -1)
        terminal.write('\b \b')
      }
    } else if (data === '\x03') {
      terminal.writeln('^C')
      currentLine = ''
    } else if (data >= ' ') {
      currentLine += data
      terminal.write(data)
    }
  })

  resizeObserver = new ResizeObserver(() => {
    fitAddon?.fit()
  })
  resizeObserver.observe(terminalContainer.value)
})

function connectWs() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  ws = new WebSocket(`${protocol}//${location.host}/ws/terminal/${props.projectId}`)

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data)
    if (msg.type === 'stdout') {
      terminal.write(msg.data)
    } else if (msg.type === 'stderr') {
      terminal.write(`\x1b[31m${msg.data}\x1b[0m`)
    } else if (msg.type === 'exit') {
      terminal.writeln(`\r\n\x1b[90m[exit code: ${msg.data}]\x1b[0m`)
    } else if (msg.type === 'error') {
      terminal.writeln(`\r\n\x1b[31m[error] ${msg.data}\x1b[0m`)
    }
  }

  ws.onclose = () => {
    terminal.writeln('\r\n\x1b[33m[disconnected]\x1b[0m')
  }
}

function sendCommand(command) {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ command }))
  } else {
    terminal.writeln('\x1b[31m[not connected]\x1b[0m')
    connectWs()
  }
}

watch(() => props.projectId, () => {
  ws?.close()
  connectWs()
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  ws?.close()
  terminal?.dispose()
})

defineExpose({ sendCommand })
</script>

<style scoped>
.xterm-terminal {
  width: 100%;
  height: 100%;
  padding: 4px;
  background: #1e1e2e;
}
</style>
