<script setup>
import { computed, ref, watch } from 'vue'
import { drumsApi } from '../api.js'
import { formatTime } from '../lib/pages.js'
import { TIMES, exportName, rowState, settingsBody, timeText } from '../lib/drums.js'
import DrumPage from '../components/DrumPage.vue'
import MappingPanel from '../components/MappingPanel.vue'

const props = defineProps({ job: { type: Object, required: true } })
const emit = defineEmits(['update', 'restart'])
const working = ref(null) // id of the page being re-recognized
const error = ref('')
const time = ref('auto')
const tempo = ref(120)
const applying = ref(false)

watch(
  () => [props.job.id, props.job.time, props.job.tempo],
  () => {
    time.value = props.job.time ? props.job.time.join('/') : 'auto'
    tempo.value = props.job.tempo
  },
  { immediate: true },
)

const failed = computed(() => props.job.pages.filter((p) => p.ok === false).length)
const recognized = computed(() => props.job.pages.some((p) => p.ok))
const measures = computed(() => props.job.pages.reduce((n, p) => n + (p.ok ? p.measures || 0 : 0), 0))
const summed = computed(() => props.job.pages.reduce((n, p) => n + (p.ok ? p.summed || 0 : 0), 0))
const busy = computed(() => working.value !== null || applying.value)

async function remove(page, index) {
  if (!confirm(`删除第 ${index + 1} 页？导出时将不再包含它。`)) return
  error.value = ''
  try {
    emit('update', await drumsApi.deletePage(props.job.id, page.id))
  } catch (e) {
    error.value = e.message
  }
}

async function rerun(page) {
  error.value = ''
  working.value = page.id
  try {
    emit('update', await drumsApi.recognizePage(props.job.id, page.id))
  } catch (e) {
    error.value = e.message
  } finally {
    working.value = null
  }
}

async function applySettings() {
  error.value = ''
  applying.value = true
  try {
    emit('update', await drumsApi.setSettings(props.job.id, settingsBody(time.value, tempo.value)))
  } catch (e) {
    error.value = e.message
  } finally {
    applying.value = false
  }
}
</script>

<template>
  <div class="card">
    <h2>
      识别结果（共 {{ job.pages.length }} 页，{{ measures }} 小节，{{ summed }} 小节时值对齐<template
        v-if="failed"
        >，{{ failed }} 页失败</template
      >）
    </h2>
    <p>
      每一页：左边是视频截图，右边是识别结果。不需要的页可以删除；识别得不对可以重新识别（会换一种方式再读一次）。
      逐个音符的修改请导出后在 MuseScore 等软件中进行。
    </p>
    <p v-if="job.status === 'failed'" class="error">{{ job.error }}</p>
    <div class="row">
      <template v-if="recognized">
        <a class="button primary" :href="drumsApi.musicxmlUrl(job.id)" :download="exportName(job, 'musicxml')">
          导出 MusicXML
        </a>
        <a class="button primary" :href="drumsApi.midiUrl(job.id)" :download="exportName(job, 'mid')">
          导出 MIDI
        </a>
      </template>
      <button @click="emit('restart')">换一个视频</button>
    </div>
    <form class="row settings" @submit.prevent="applySettings">
      <label>
        拍号：
        <select v-model="time" :disabled="busy">
          <option value="auto">按视频识别（当前 {{ timeText({ ...job, time: null }) }}）</option>
          <option v-for="t in TIMES" :key="t" :value="t">{{ t }}</option>
        </select>
      </label>
      <label>
        速度（每分钟四分音符）：
        <input v-model="tempo" type="number" min="20" max="400" step="1" :disabled="busy" />
      </label>
      <button :disabled="busy">{{ applying ? '应用中…' : '应用' }}</button>
      <span class="meta">改拍号会按新拍号重新识别每一页；改速度只影响导出。</span>
    </form>
    <p v-if="error" class="error">{{ error }}</p>
  </div>
  <MappingPanel v-if="recognized" :job="job" @update="emit('update', $event)" />
  <div v-for="(p, i) in job.pages" :key="p.id" class="card page" :class="rowState(p).kind">
    <div class="row head">
      <strong>第 {{ i + 1 }} 页</strong>
      <span class="meta">{{ formatTime(p.start) }} – {{ formatTime(p.end) }}</span>
      <span v-if="rowState(p).label" class="state">{{ rowState(p).label }}</span>
      <span class="spacer" />
      <button :disabled="busy" @click="rerun(p)">
        {{ working === p.id ? '识别中…' : '重新识别' }}
      </button>
      <button :disabled="busy" @click="remove(p, i)">删除</button>
    </div>
    <div class="pair">
      <img :src="drumsApi.fileUrl(job.id, p.image)" alt="视频截图" />
      <DrumPage :job-id="job.id" :page="p" />
    </div>
  </div>
  <div v-if="job.pages.length > 3 && recognized" class="card row">
    <a class="button primary" :href="drumsApi.musicxmlUrl(job.id)" :download="exportName(job, 'musicxml')">
      导出 MusicXML
    </a>
    <a class="button primary" :href="drumsApi.midiUrl(job.id)" :download="exportName(job, 'mid')">
      导出 MIDI
    </a>
  </div>
</template>

<style scoped>
.head { margin-bottom: 8px; }
.meta { color: #666; font-size: 13px; }
.spacer { flex: 1; }
.settings { margin-top: 12px; gap: 16px; }
.settings input { width: 80px; }
.state { font-size: 13px; padding: 2px 8px; border-radius: 4px; background: #eee; }
.page.failed { box-shadow: inset 4px 0 0 #dc2626, 0 1px 3px rgba(0, 0, 0, 0.08); }
.page.failed .state { background: #fee2e2; color: #b91c1c; }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: start; }
.pair img { width: 100%; display: block; border: 1px solid #eee; }
a.button { display: inline-block; padding: 6px 14px; border-radius: 6px; text-decoration: none; }
a.button.primary { background: #2563eb; color: #fff; }
@media (max-width: 800px) { .pair { grid-template-columns: 1fr; } }
</style>
