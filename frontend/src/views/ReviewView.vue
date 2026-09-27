<script setup>
import { ref } from 'vue'
import { api } from '../api.js'
import { formatTime, moveItem } from '../lib/pages.js'

const props = defineProps({ job: { type: Object, required: true } })
const emit = defineEmits(['back', 'restart'])

const pages = ref(props.job.pages.slice())
const dragFrom = ref(null)
const links = ref({})
const error = ref('')

function remove(index) {
  pages.value = pages.value.filter((_, i) => i !== index)
}

function onDragStart(event, index) {
  dragFrom.value = index
  // Firefox refuses to start a drag unless data is set on the dataTransfer.
  event.dataTransfer.setData('text/plain', '')
}

function onDrop(index) {
  if (dragFrom.value !== null) pages.value = moveItem(pages.value, dragFrom.value, index)
  dragFrom.value = null
}

function duplicateLabel(dupId) {
  const original = props.job.pages.find((p) => p.id === dupId)
  return original ? `重复：同 ${formatTime(original.start)} 段` : '重复'
}

async function exportAs(fmt) {
  error.value = ''
  try {
    const res = await api.exportPages(props.job.id, pages.value.map((p) => p.id), fmt)
    links.value = { ...links.value, [fmt]: `${res.url}?v=${Date.now()}` }
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <div class="card">
    <h2>3. 校对并导出（共 {{ pages.length }} 页）</h2>
    <p>拖动调整顺序，点 × 删除多余页面。标记"重复"的页面与前面某页内容相同（例如副歌重现）。</p>
    <div class="row">
      <button class="primary" :disabled="!pages.length" @click="exportAs('png')">导出长图 PNG</button>
      <button class="primary" :disabled="!pages.length" @click="exportAs('pdf')">导出 PDF</button>
      <a v-if="links.png" :href="links.png" target="_blank">打开 PNG</a>
      <a v-if="links.pdf" :href="links.pdf" target="_blank">打开 PDF</a>
      <button @click="pages = job.pages.slice()">恢复全部</button>
      <button @click="emit('back')">重新框选</button>
      <button @click="emit('restart')">换一个视频</button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
  </div>
  <div
    v-for="(page, i) in pages"
    :key="page.id"
    class="card page"
    draggable="true"
    @dragstart="onDragStart($event, i)"
    @dragover.prevent
    @drop="onDrop(i)"
  >
    <div class="row meta">
      <strong>#{{ i + 1 }}</strong>
      <a :href="api.frameUrl(job.id, page.start)" target="_blank">
        {{ formatTime(page.start) }} – {{ formatTime(page.end) }}
      </a>
      <span v-if="page.duplicate_of !== null" class="dup">{{ duplicateLabel(page.duplicate_of) }}</span>
      <button class="remove" title="删除" @click="remove(i)">×</button>
    </div>
    <img :src="api.fileUrl(job.id, page.file)" draggable="false" />
  </div>
</template>

<style scoped>
.page { cursor: grab; }
.page img { display: block; max-width: 100%; }
.meta { margin-bottom: 8px; }
.dup { background: #e0e7ff; padding: 2px 8px; border-radius: 4px; font-size: 13px; }
.remove { margin-left: auto; }
</style>
