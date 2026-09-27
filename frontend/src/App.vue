<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { api } from './api.js'
import InputView from './views/InputView.vue'
import RegionEditor from './views/RegionEditor.vue'
import ReviewView from './views/ReviewView.vue'

const job = ref(null)
const STAGES = { download: '下载视频', probe: '检测谱面区域', scan: '扫描换页', compose: '合成页面' }
let timer = null

function track(next) {
  job.value = next
  clearTimeout(timer)
  if (next.status === 'downloading' || next.status === 'analyzing') {
    timer = setTimeout(async () => {
      try {
        track(await api.getJob(next.id))
      } catch (e) {
        track({ ...next, status: 'failed', error: e.message })
      }
    }, 800)
  }
}

function restart() {
  clearTimeout(timer)
  job.value = null
}

onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <main>
    <h1>Video → Tab</h1>
    <InputView v-if="!job" @created="track" />
    <template v-else>
      <div v-if="job.status === 'downloading' || job.status === 'analyzing'" class="card">
        <p>{{ STAGES[job.stage] || '处理中' }}…</p>
        <progress :value="job.progress" max="1" />
      </div>
      <div v-else-if="job.status === 'failed'" class="card">
        <p class="error">{{ job.error }}</p>
        <div class="row">
          <button v-if="job.region" @click="track({ ...job, status: 'ready_for_region' })">
            调整区域重试
          </button>
          <button @click="restart">重新开始</button>
        </div>
      </div>
      <RegionEditor v-else-if="job.status === 'ready_for_region'" :job="job" @started="track" />
      <ReviewView
        v-else-if="job.status === 'ready_for_review'"
        :job="job"
        @back="track({ ...job, status: 'ready_for_region' })"
        @restart="restart"
      />
    </template>
  </main>
</template>
