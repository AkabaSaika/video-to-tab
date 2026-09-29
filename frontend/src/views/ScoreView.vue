<script setup>
// The score page: settings (title, tempo, tuning), the rendered tab, the beat editor,
// autosave to the backend and .gp export.
import { computed, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { api } from '../api.js'
import BeatEditor from '../components/BeatEditor.vue'
import TabRenderer from '../components/TabRenderer.vue'
import { scoreTuning } from '../lib/alphatex.js'
import { createAutosaver } from '../lib/autosave.js'
import { needsReview, nextToReview } from '../lib/scoreEdit.js'
import { PRESETS, parseTuning, tuningText } from '../lib/tuning.js'

const props = defineProps({ job: { type: Object, required: true } })
const emit = defineEmits(['back'])

const score = shallowRef(null)
const selected = ref(null)
const loadError = ref('')
const renderError = ref('')
const exportError = ref('')
const saveState = ref('saved') // saved | pending | saving | unsaved
const renderer = ref(null)

onMounted(async () => {
  try {
    score.value = await api.getScore(props.job.id)
  } catch (e) {
    loadError.value = e.message
  }
})

// ------------------------------------------------------------------ autosave

const saver = createAutosaver({
  save: (value) => api.saveScore(props.job.id, value),
  onState: (s) => (saveState.value = s),
  delay: 1000, // ms of quiet before an autosave
  retryDelay: 5000, // a failed save is retried on its own
})

function update(next, sel) {
  score.value = next
  if (sel !== undefined) selected.value = sel
  saver.change(next)
}

// Leaving with unsaved edits: ask first (a score is too big for a keepalive request).
function warnIfUnsaved(event) {
  if (saver.isClean()) return
  saver.flush()
  event.preventDefault()
  event.returnValue = ''
}

onMounted(() => window.addEventListener('beforeunload', warnIfUnsaved))
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', warnIfUnsaved)
  saver.flush()
})

const SAVE_TEXT = { saved: '已保存', pending: '待保存…', saving: '保存中…', unsaved: '未保存' }

// ------------------------------------------------------------------ settings

const title = computed({
  get: () => score.value.title,
  set: (title) => update({ ...score.value, title: title.trim() }),
})

const tempo = computed({
  get: () => score.value.tempo ?? 120,
  set: (v) => {
    const t = Math.round(Number(v))
    if (t >= 20 && t <= 400) update({ ...score.value, tempo: t })
  },
})

const presets = computed(() => PRESETS[score.value.strings] ?? [])
const tuningNow = computed(() => tuningText(scoreTuning(score.value)))
const presetName = computed(() => {
  const hit = presets.value.find((p) => tuningText(p.tuning) === tuningNow.value)
  return hit ? hit.name : 'custom'
})
const tuningError = ref('')

function choosePreset(event) {
  const preset = presets.value.find((p) => p.name === event.target.value)
  if (preset) update({ ...score.value, tuning: preset.tuning.slice() })
}

function customTuning(event) {
  try {
    update({ ...score.value, tuning: parseTuning(event.target.value, score.value.strings) })
    tuningError.value = ''
  } catch (e) {
    tuningError.value = e.message
  }
}

// ------------------------------------------------------------------ review + export

const toReview = computed(() => {
  let n = 0
  for (const m of score.value.measures) for (const b of m.beats) n += needsReview(m, b) ? 1 : 0
  return n
})

function next() {
  const pos = nextToReview(score.value, selected.value)
  if (pos) selected.value = pos
}

function exportGp() {
  exportError.value = ''
  try {
    const bytes = renderer.value.exportGp()
    const name = `${(score.value.title || 'tab').replace(/[\\/:*?"<>|]/g, '_')}.gp`
    const url = URL.createObjectURL(new Blob([bytes], { type: 'application/octet-stream' }))
    const a = document.createElement('a')
    a.href = url
    a.download = name
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) {
    exportError.value = `导出失败：${e.message}`
  }
}
</script>

<template>
  <div v-if="loadError" class="card">
    <p class="error">{{ loadError }}</p>
    <button @click="emit('back')">回到校对页</button>
  </div>
  <template v-else-if="score">
    <div class="card">
      <h2>4. 识谱结果（{{ score.measures.length }} 小节，{{ score.strings }} 弦）</h2>
      <div class="row settings">
        <label>标题 <input v-model.lazy="title" type="text" placeholder="未命名" size="24" /></label>
        <label>速度 <input v-model.lazy="tempo" type="number" min="20" max="400" /></label>
        <label>
          定弦
          <select :value="presetName" @change="choosePreset">
            <option v-for="p in presets" :key="p.name" :value="p.name">{{ p.name }}</option>
            <option value="custom">自定义</option>
          </select>
        </label>
        <input
          :key="tuningNow"
          type="text"
          :value="tuningNow"
          size="26"
          title="从最高音弦写到最低音弦，例如 E4 B3 G3 D3 A2 E2"
          @change="customTuning"
        />
      </div>
      <p v-if="tuningError" class="error">{{ tuningError }}</p>
      <div class="row">
        <button :disabled="!toReview" @click="next">下一个待检查（{{ toReview }}）</button>
        <button class="primary" @click="exportGp">导出 .gp</button>
        <button @click="emit('back')">回到校对页</button>
        <span class="save" :class="saveState">{{ SAVE_TEXT[saveState] }}</span>
      </div>
      <p class="hint">橙色 = 需要检查的拍；点击任意一拍即可修改。</p>
      <p v-if="exportError" class="error">{{ exportError }}</p>
      <p v-if="renderError" class="error">{{ renderError }}</p>
    </div>
    <div class="workspace">
      <div class="card sheet">
        <TabRenderer
          ref="renderer"
          :score="score"
          :selected="selected"
          @select="selected = $event"
          @error="renderError = $event"
          @rendered="renderError = ''"
        />
      </div>
      <BeatEditor
        v-if="selected && score.measures[selected.m]"
        class="side"
        :job="job"
        :score="score"
        :m="selected.m"
        :b="selected.b"
        @change="update"
        @close="selected = null"
      />
    </div>
  </template>
  <p v-else class="card">正在加载识谱结果…</p>
</template>

<style scoped>
.settings label input[type='number'] { width: 70px; }
.workspace { display: flex; gap: 16px; align-items: flex-start; }
.sheet { flex: 1; min-width: 0; }
.side { position: sticky; top: 8px; flex: none; max-height: calc(100vh - 16px); overflow: auto; }
.save { margin-left: auto; font-size: 13px; color: #15803d; }
.save.pending, .save.saving { color: #666; }
.save.unsaved { color: #b91c1c; font-weight: 600; }
.hint { color: #666; font-size: 13px; margin: 8px 0 0; }
</style>
