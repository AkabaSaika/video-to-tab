<script setup>
import { ref, watch } from 'vue'
import { pianoApi } from '../api.js'
import { renderSystem } from '../lib/verovio.js'

const props = defineProps({
  jobId: { type: String, required: true },
  system: { type: Object, required: true },
})
const svg = ref('')
const message = ref('')

async function render() {
  svg.value = ''
  const s = props.system
  if (!s.ok || !s.musicxml) {
    message.value = s.ok === false ? '没有识别结果' : '等待识别…'
    return
  }
  message.value = '正在显示…'
  try {
    // attempts changes on every re-recognition, so the browser never shows a stale file
    const res = await fetch(`${pianoApi.fileUrl(props.jobId, s.musicxml)}?v=${s.attempts ?? 0}`)
    if (!res.ok) throw new Error(`读取识别结果失败 (${res.status})`)
    svg.value = await renderSystem(await res.text())
    message.value = ''
  } catch (e) {
    message.value = e.message
  }
}

watch(() => [props.system.ok, props.system.musicxml, props.system.attempts], render, {
  immediate: true,
})
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -- SVG made by Verovio from our own MusicXML -->
  <div v-if="svg" class="score" v-html="svg" />
  <div v-else class="score empty">{{ message }}</div>
</template>

<style scoped>
.score { background: #fff; border: 1px solid #eee; min-height: 60px; }
.empty { display: flex; align-items: center; justify-content: center; color: #999; font-size: 14px; }
</style>
