<script setup>
import { onMounted, ref } from 'vue'
import { pianoApi } from '../api.js'
import { STATUS } from '../lib/piano.js'

const emit = defineEmits(['created'])
const url = ref('')
const error = ref('')
const busy = ref(false)
const recent = ref([])

onMounted(async () => {
  try {
    recent.value = await pianoApi.listJobs()
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
  if (file) submit(() => pianoApi.createFromFile(file))
}

function when(seconds) {
  return new Date(seconds * 1000).toLocaleString()
}
</script>

<template>
  <div class="card">
    <h2>钢琴谱识别</h2>
    <p>
      上传显示五线谱（大谱表）的钢琴演奏视频，自动截取每一行谱表、识别并导出 MusicXML，可在
      MuseScore 等软件中打开编辑。
    </p>
    <p>上传本地视频（mp4 / mkv / webm / mov / avi / flv …）</p>
    <input type="file" accept="video/*,.mkv,.flv" :disabled="busy" @change="onFile" />
    <p>或粘贴 bilibili / YouTube 链接、BV 号：</p>
    <form class="row" @submit.prevent="submit(() => pianoApi.createFromUrl(url))">
      <input v-model="url" type="text" placeholder="https://www.youtube.com/watch?v=..." size="50" />
      <button class="primary" :disabled="busy || !url.trim()">开始识别</button>
    </form>
    <p v-if="error" class="error">{{ error }}</p>
  </div>
  <div v-if="recent.length" class="card">
    <h2>最近的钢琴任务</h2>
    <ul class="recent">
      <li v-for="j in recent" :key="j.id">
        <button :disabled="busy" @click="submit(() => pianoApi.getJob(j.id))">
          {{ j.title || j.source || j.id }}
        </button>
        <span class="meta">
          {{ STATUS[j.status] || j.status }}<template v-if="j.systems"> · {{ j.systems }} 组</template>
          · {{ when(j.created) }}
        </span>
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
