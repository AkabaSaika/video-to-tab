<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'

const emit = defineEmits(['created'])
const url = ref('')
const error = ref('')
const busy = ref(false)
const recent = ref([])
const STATUS = {
  downloading: '下载中',
  ready_for_region: '待框选',
  analyzing: '分析中',
  ready_for_review: '待校对',
  recognizing: '识谱中',
  ready_for_score: '已识谱',
  failed: '失败',
}

onMounted(async () => {
  try {
    recent.value = await api.listJobs()
  } catch {
    recent.value = [] // the list is a convenience; never block starting a new job
  }
})

async function submit(action) {
  error.value = ''
  busy.value = true
  try {
    emit('created', await action())
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

function onFile(event) {
  const file = event.target.files[0]
  if (file) submit(() => api.createFromFile(file))
}

function when(seconds) {
  return new Date(seconds * 1000).toLocaleString()
}
</script>

<template>
  <div class="card">
    <h2>1. 选择视频</h2>
    <p>上传本地视频（mp4 / mkv / webm / mov / avi / flv …）</p>
    <input type="file" accept="video/*,.mkv,.flv" :disabled="busy" @change="onFile" />
    <p>或粘贴 bilibili / YouTube 链接、BV 号：</p>
    <form class="row" @submit.prevent="submit(() => api.createFromUrl(url))">
      <input v-model="url" type="text" placeholder="https://www.bilibili.com/video/BV..." size="50" />
      <button class="primary" :disabled="busy || !url.trim()">解析</button>
    </form>
    <p v-if="error" class="error">{{ error }}</p>
  </div>
  <div v-if="recent.length" class="card">
    <h2>最近的任务</h2>
    <ul class="recent">
      <li v-for="j in recent" :key="j.id">
        <button :disabled="busy" @click="submit(() => api.getJob(j.id))">
          {{ j.title || j.source || j.id }}
        </button>
        <span class="meta">{{ STATUS[j.status] || j.status }} · {{ when(j.created) }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.recent { list-style: none; padding: 0; margin: 0; }
.recent li { display: flex; gap: 12px; align-items: center; padding: 4px 0; }
.recent button { max-width: 60%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; }
.meta { color: #666; font-size: 13px; }
</style>
