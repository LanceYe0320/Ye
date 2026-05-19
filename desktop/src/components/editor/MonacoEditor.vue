<template>
  <div ref="editorContainer" class="monaco-editor"></div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as monaco from 'monaco-editor'

const props = defineProps({
  modelValue: { type: String, default: '' },
  language: { type: String, default: 'plaintext' },
  filePath: { type: String, default: '' },
  readOnly: { type: Boolean, default: false },
  theme: { type: String, default: 'vs-dark' },
})

const emit = defineEmits(['update:modelValue', 'save'])

const editorContainer = ref(null)
let editor = null

const LANG_MAP = {
  js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript',
  py: 'python', java: 'java', c: 'c', cpp: 'cpp', h: 'cpp',
  cs: 'csharp', go: 'go', rs: 'rust', rb: 'ruby', php: 'php',
  html: 'html', htm: 'html', css: 'css', scss: 'scss', less: 'less',
  json: 'json', yaml: 'yaml', yml: 'yaml', xml: 'xml', svg: 'xml',
  md: 'markdown', sql: 'sql', sh: 'shell', bash: 'shell',
  dockerfile: 'dockerfile', toml: 'ini', ini: 'ini', env: 'ini',
  vue: 'html', dart: 'dart', kt: 'kotlin', swift: 'swift',
}

function detectLanguage(path) {
  if (!path) return 'plaintext'
  const ext = path.split('.').pop().toLowerCase()
  return LANG_MAP[ext] || 'plaintext'
}

onMounted(() => {
  const lang = props.language !== 'plaintext' ? props.language : detectLanguage(props.filePath)

  editor = monaco.editor.create(editorContainer.value, {
    value: props.modelValue,
    language: lang,
    theme: props.theme,
    readOnly: props.readOnly,
    automaticLayout: true,
    minimap: { enabled: true },
    fontSize: 14,
    lineNumbers: 'on',
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    tabSize: 4,
    renderWhitespace: 'selection',
    bracketPairColorization: { enabled: true },
    padding: { top: 8 },
  })

  editor.onDidChangeModelContent(() => {
    emit('update:modelValue', editor.getValue())
  })

  editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
    emit('save', editor.getValue())
  })
})

watch(() => props.modelValue, (newVal) => {
  if (editor && editor.getValue() !== newVal) {
    const model = editor.getModel()
    if (model) {
      editor.pushUndoStop()
      model.setValue(newVal)
    }
  }
})

watch(() => props.language, (newLang) => {
  if (editor) {
    const lang = newLang !== 'plaintext' ? newLang : detectLanguage(props.filePath)
    monaco.editor.setModelLanguage(editor.getModel(), lang)
  }
})

watch(() => props.readOnly, (val) => {
  editor?.updateOptions({ readOnly: val })
})

onBeforeUnmount(() => {
  editor?.dispose()
})

function getEditor() {
  return editor
}

function focus() {
  editor?.focus()
}

defineExpose({ getEditor, focus })
</script>

<style scoped>
.monaco-editor {
  width: 100%;
  height: 100%;
  min-height: 200px;
}
</style>
