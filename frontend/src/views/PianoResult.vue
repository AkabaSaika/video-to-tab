<script setup>
import { computed, ref } from 'vue'
import { pianoApi } from '../api.js'
import { formatTime } from '../lib/pages.js'
import { exportName, rowState, withoutSystem } from '../lib/piano.js'
import SystemScore from '../components/SystemScore.vue'

const props = defineProps({ job: { type: Object, required: true } })
const emit = defineEmits(['update', 'restart'])
const working = ref(null) // id of the system being re-recognized
const error = ref('')

const failed = computed(() => props.job.systems.filter((s) => s.ok === false).length)
const recognized = computed(() => props.job.systems.some((s) => s.ok))

async function remove(system, index) {
  if (!confirm(`删除第 ${index + 1} 组谱表？导出时将不再包含它。`)) return
  error.value = ''
  try {
    emit('update', await pianoApi.deleteSystem(props.job.id, system.id))
  } catch (e) {
    error.value = e.message
    emit('update', withoutSystem(props.job, -1))
  }
}

async function rerun(system) {
  error.value = ''
  working.value = system.id
  try {
    emit('update', await pianoApi.recognizeSystem(props.job.id, system.id))
  } catch (e) {
    error.value = e.message
  } finally {
    working.value = null
  }
}
</script>

<template>
  <div class="card">
    <h2>识别结果（共 {{ job.systems.length }} 组<template v-if="failed">，{{ failed }} 组失败</template>）</h2>
    <p>
      每一组：左边是视频截图，右边是识别结果。不需要的组可以删除；识别得不对可以重新识别（会换一种方式再读一次）。
    </p>
    <p v-if="job.status === 'failed'" class="error">{{ job.error }}</p>
    <div class="row">
      <a
        v-if="recognized"
        class="button primary"
        :href="pianoApi.musicxmlUrl(job.id)"
        :download="exportName(job)"
      >
        导出 MusicXML
      </a>
      <button @click="emit('restart')">换一个视频</button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
  </div>
  <div v-for="(s, i) in job.systems" :key="s.id" class="card system" :class="rowState(s).kind">
    <div class="row head">
      <strong>第 {{ i + 1 }} 组</strong>
      <span class="meta">{{ formatTime(s.start) }} – {{ formatTime(s.end) }}</span>
      <span v-if="rowState(s).label" class="state">{{ rowState(s).label }}</span>
      <span class="spacer" />
      <button :disabled="working !== null" @click="rerun(s)">
        {{ working === s.id ? '识别中…' : '重新识别' }}
      </button>
      <button :disabled="working !== null" @click="remove(s, i)">删除</button>
    </div>
    <div class="pair">
      <img :src="pianoApi.fileUrl(job.id, s.image)" alt="视频截图" />
      <SystemScore :job-id="job.id" :system="s" />
    </div>
  </div>
  <div v-if="job.systems.length > 3 && recognized" class="card row">
    <a class="button primary" :href="pianoApi.musicxmlUrl(job.id)" :download="exportName(job)">
      导出 MusicXML
    </a>
  </div>
</template>

<style scoped>
.head { margin-bottom: 8px; }
.meta { color: #666; font-size: 13px; }
.spacer { flex: 1; }
.state { font-size: 13px; padding: 2px 8px; border-radius: 4px; background: #eee; }
.system.failed { box-shadow: inset 4px 0 0 #dc2626, 0 1px 3px rgba(0, 0, 0, 0.08); }
.system.failed .state { background: #fee2e2; color: #b91c1c; }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: start; }
.pair img { width: 100%; display: block; border: 1px solid #eee; }
a.button { display: inline-block; padding: 6px 14px; border-radius: 6px; text-decoration: none; }
a.button.primary { background: #2563eb; color: #fff; }
@media (max-width: 800px) { .pair { grid-template-columns: 1fr; } }
</style>
