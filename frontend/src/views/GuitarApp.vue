<script setup>
import { defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
import { guitarHash, parseHash, replaceHash } from '../lib/route.js'
import InputView from './InputView.vue'
import RegionEditor from './RegionEditor.vue'
import ReviewView from './ReviewView.vue'

// alphaTab is large: load the score page only when it is first shown
const ScoreView = defineAsyncComponent(() => import('./ScoreView.vue'))

// the guitar pages stay alive while the piano page is shown; only the shown page owns the URL
const props = defineProps({ active: { type: Boolean, default: true } })

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
  if (props.active) replaceHash(guitarHash(id))
}

watch(
  () => props.active,
  (active) => active && setHash(job.value?.id),
)

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
  const { page, job: id } = parseHash(location.hash)
  if (page !== 'guitar' || !id) return
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
  <div>
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
  </div>
</template>
