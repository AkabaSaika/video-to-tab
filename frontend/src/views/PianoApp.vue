<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { pianoApi } from '../api.js'
import { BUSY, progressText } from '../lib/piano.js'
import { parseHash, pianoHash, replaceHash } from '../lib/route.js'
import PianoInput from './PianoInput.vue'
import PianoResult from './PianoResult.vue'

const props = defineProps({ active: { type: Boolean, default: true } })
const job = ref(null)
const restoreError = ref('')
const STAGES = [
  ['downloading', '下载视频'],
  ['capturing', '截取谱表'],
  ['recognizing', '识别'],
]
let timer = null

function setHash(id) {
  if (props.active) replaceHash(pianoHash(id))
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
        track(await pianoApi.getJob(next.id))
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

function stageClass(status) {
  const order = STAGES.map(([s]) => s)
  const now = order.indexOf(job.value.status)
  const at = order.indexOf(status)
  return at < now ? 'done' : at === now ? 'now' : ''
}

onMounted(async () => {
  const { page, job: id } = parseHash(location.hash)
  if (page !== 'piano' || !id) {
    setHash(null) // opened from the guitar page: show the piano page's own URL
    return
  }
  try {
    track(await pianoApi.getJob(id))
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
      <PianoInput @created="track" />
    </template>
    <template v-else>
      <div v-if="BUSY.includes(job.status)" class="card">
        <ol class="stages">
          <li v-for="[status, label] in STAGES" :key="status" :class="stageClass(status)">
            {{ label }}
          </li>
        </ol>
        <p>{{ progressText(job) }}</p>
        <progress :value="job.progress" max="1" />
      </div>
      <div v-else-if="job.status === 'failed' && !job.systems.length" class="card">
        <p class="error">{{ job.error }}</p>
        <button @click="restart">重新开始</button>
      </div>
      <PianoResult v-else :job="job" @update="track" @restart="restart" />
    </template>
  </div>
</template>

<style scoped>
.stages { display: flex; gap: 24px; list-style: none; padding: 0; margin: 0 0 8px; color: #999; }
.stages li.done { color: #15803d; }
.stages li.now { color: #1d4ed8; font-weight: 600; }
</style>
