<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { drumsApi } from '../api.js'
import { BUSY, progressText } from '../lib/drums.js'
import { drumsHash, parseHash, replaceHash } from '../lib/route.js'
import DrumsInput from './DrumsInput.vue'
import DrumsResult from './DrumsResult.vue'

const props = defineProps({ active: { type: Boolean, default: true } })
const job = ref(null)
const restoreError = ref('')
const STAGES = [
  ['downloading', '下载视频'],
  ['capturing', '截取谱面'],
  ['recognizing', '识别'],
]
let timer = null

function setHash(id) {
  if (props.active) replaceHash(drumsHash(id))
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
        track(await drumsApi.getJob(next.id))
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
  if (page !== 'drums' || !id) {
    setHash(null) // opened from another page: show the drum page's own URL
    return
  }
  try {
    track(await drumsApi.getJob(id))
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
      <DrumsInput @created="track" />
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
      <div v-else-if="job.status === 'failed' && !job.pages.length" class="card">
        <p class="error">{{ job.error }}</p>
        <button @click="restart">重新开始</button>
      </div>
      <DrumsResult v-else :job="job" @update="track" @restart="restart" />
    </template>
  </div>
</template>

<style scoped>
.stages { display: flex; gap: 24px; list-style: none; padding: 0; margin: 0 0 8px; color: #999; }
.stages li.done { color: #15803d; }
.stages li.now { color: #1d4ed8; font-weight: 600; }
</style>
