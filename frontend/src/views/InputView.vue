<script setup>
import { ref } from 'vue'
import { api } from '../api.js'

const emit = defineEmits(['created'])
const url = ref('')
const error = ref('')
const busy = ref(false)

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
</template>
