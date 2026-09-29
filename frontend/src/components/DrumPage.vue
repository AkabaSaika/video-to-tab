<script setup>
import { ref, watch } from 'vue'
import { drumsApi } from '../api.js'
import { renderSystem } from '../lib/verovio.js'

const props = defineProps({
  jobId: { type: String, required: true },
  page: { type: Object, required: true },
})
const svg = ref('')
const message = ref('')

async function render() {
  svg.value = ''
  const p = props.page
  if (!p.ok || !p.musicxml) {
    message.value = p.ok === false ? '没有识别结果' : '等待识别…'
    return
  }
  message.value = '正在显示…'
  try {
    // rev changes whenever the preview is rewritten (new mapping, new try), so the
    // browser never shows a stale file
    const res = await fetch(`${drumsApi.fileUrl(props.jobId, p.musicxml)}?v=${p.attempts ?? 0}-${p.rev ?? 0}`)
    if (!res.ok) throw new Error(`读取识别结果失败 (${res.status})`)
    svg.value = await renderSystem(await res.text())
    message.value = ''
  } catch (e) {
    message.value = e.message
  }
}

watch(() => [props.page.ok, props.page.musicxml, props.page.attempts, props.page.rev], render, {
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
