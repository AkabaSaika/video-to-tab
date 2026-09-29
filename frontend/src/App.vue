<script setup>
import { defineAsyncComponent, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from './api.js'
import InputView from './views/InputView.vue'
import RegionEditor from './views/RegionEditor.vue'
import ReviewView from './views/ReviewView.vue'

// alphaTab is large: load the score page only when it is first shown
const ScoreView = defineAsyncComponent(() => import('./views/ScoreView.vue'))

const job = ref(null)
const restoreError = ref('')
const STAGES = {
  download: '下载视频',
  probe: '检测谱面区域',
  scan: '扫描换页',
  compose: '合成页面',
  recognize: '识谱',
}
const BUSY = ['downloading', 'analyzing', 'recognizing']
let timer = null

function setHash(id) {
  const hash = id ? `#job=${id}` : ''
  if (location.hash !== hash) history.replaceState(null, '', `${location.pathname}${location.search}${hash}`)
}

function track(next) {
  job.value = next
  setHash(next.id)
  clearTimeout(timer)
  if (BUSY.includes(next.status)) {
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
  setHash(null)
}

onMounted(async () => {
  const id = /^#job=([\w-]+)$/.exec(location.hash)?.[1]
  if (!id) return
  try {
    track(await api.getJob(id))
  } catch (e) {
    restoreError.value = `无法恢复任务 ${id}：${e.message}`
    setHash(null)
  }
})

onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <main>
    <h1>Video → Tab</h1>
    <template v-if="!job">
      <p v-if="restoreError" class="error card">{{ restoreError }}</p>
      <InputView @created="track" />
    </template>
    <template v-else>
      <div v-if="BUSY.includes(job.status)" class="card">
        <p>{{ STAGES[job.stage] || '处理中' }}…</p>
        <progress :value="job.progress" max="1" />
      </div>
      <div v-else-if="job.status === 'failed'" class="card">
        <p class="error">{{ job.error }}</p>
        <div class="row">
          <button v-if="job.pages.length" @click="track({ ...job, status: 'ready_for_review' })">
            回到校对页
          </button>
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
        @started="track"
        @score="track({ ...job, status: 'ready_for_score' })"
      />
      <ScoreView
        v-else-if="job.status === 'ready_for_score'"
        :key="job.id"
        :job="job"
        @back="track({ ...job, status: 'ready_for_review' })"
      />
    </template>
  </main>
</template>
