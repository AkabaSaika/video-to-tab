<script setup>
// The score page: song settings (title, tempo), the track switcher with each track's name
// and tuning, the rendered tab (all tracks), the beat editor, autosave and .gp export.
import { computed, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { api } from '../api.js'
import BeatEditor from '../components/BeatEditor.vue'
import TabRenderer from '../components/TabRenderer.vue'
import { scoreTuning } from '../lib/alphatex.js'
import { createAutosaver } from '../lib/autosave.js'
import { needsReview, nextInSong } from '../lib/scoreEdit.js'
import { setTrack, toSong, trackName } from '../lib/song.js'
import { PRESETS, parseTuning, tuningText } from '../lib/tuning.js'

const props = defineProps({ job: { type: Object, required: true } })
const emit = defineEmits(['back'])

const song = shallowRef(null)
const current = ref(0) // index of the track whose settings are shown
const selected = ref(null) // { t, m, b }
const loadError = ref('')
const renderError = ref('')
const exportError = ref('')
const saveState = ref('saved') // saved | pending | saving | unsaved
const renderer = ref(null)

onMounted(async () => {
  try {
    song.value = toSong(await api.getScore(props.job.id)) // old jobs: a single Score
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
  song.value = next
  if (sel !== undefined) selected.value = sel
  saver.change(next)
}

const track = computed(() => song.value.tracks[current.value])

// an edit of the current track (from the beat editor: selection within that track)
function updateTrack(next, sel) {
  update(setTrack(song.value, current.value, next), sel && { t: current.value, ...sel })
}

// the beat editor edits the selected beat's track
function updateBeatEdit(t, next, sel) {
  update(setTrack(song.value, t, next), sel && { t, ...sel })
}

function select(sel) {
  selected.value = sel
  if (sel) current.value = sel.t
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
  get: () => song.value.title,
  set: (title) => update({ ...song.value, title: title.trim() }),
})

const tempo = computed({
  get: () => song.value.tempo ?? 120,
  set: (v) => {
    const t = Math.round(Number(v))
    if (t >= 20 && t <= 400) update({ ...song.value, tempo: t })
  },
})

const trackLabel = computed({
  get: () => track.value.name || trackName(current.value, song.value.tracks.length),
  set: (v) => {
    const text = v.trim()
    if (text) updateTrack({ ...track.value, name: text })
  },
})

const presets = computed(() => PRESETS[track.value.strings] ?? [])
const tuningNow = computed(() => tuningText(scoreTuning(track.value)))
const presetName = computed(() => {
  const hit = presets.value.find((p) => tuningText(p.tuning) === tuningNow.value)
  return hit ? hit.name : 'custom'
})
const tuningError = ref('')

function choosePreset(event) {
  const preset = presets.value.find((p) => p.name === event.target.value)
  if (preset) updateTrack({ ...track.value, tuning: preset.tuning.slice() })
}

function customTuning(event) {
  try {
    updateTrack({ ...track.value, tuning: parseTuning(event.target.value, track.value.strings) })
    tuningError.value = ''
  } catch (e) {
    tuningError.value = e.message
  }
}

// ------------------------------------------------------------------ review + export

const toReview = computed(() => {
  let n = 0
  for (const t of song.value.tracks)
    for (const m of t.measures) for (const b of m.beats) n += needsReview(m, b) ? 1 : 0
  return n
})

function next() {
  const pos = nextInSong(song.value, selected.value)
  if (pos) select(pos)
}

function exportGp() {
  exportError.value = ''
  try {
    const bytes = renderer.value.exportGp()
    const name = `${(song.value.title || 'tab').replace(/[\\/:*?"<>|]/g, '_')}.gp`
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
  <template v-else-if="song">
    <div class="card">
      <h2>
        4. 识谱结果（{{ song.tracks.length }} 个声部，{{ track.measures.length }} 小节）
      </h2>
      <div class="row settings">
        <label>标题 <input v-model.lazy="title" type="text" placeholder="未命名" size="24" /></label>
        <label>速度 <input v-model.lazy="tempo" type="number" min="20" max="400" /></label>
      </div>
      <div v-if="song.tracks.length > 1" class="row tracks">
        <span>声部</span>
        <button
          v-for="(t, i) in song.tracks"
          :key="i"
          :class="{ on: i === current }"
          @click="current = i"
        >
          {{ t.name || trackName(i, song.tracks.length) }}
        </button>
      </div>
      <div class="row settings">
        <label>声部名 <input v-model.lazy="trackLabel" type="text" size="12" /></label>
        <span class="muted">{{ track.strings }} 弦</span>
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
          :song="song"
          :selected="selected"
          @select="select"
          @error="renderError = $event"
          @rendered="renderError = ''"
        />
      </div>
      <BeatEditor
        v-if="selected && song.tracks[selected.t]?.measures[selected.m]"
        class="side"
        :job="job"
        :score="song.tracks[selected.t]"
        :m="selected.m"
        :b="selected.b"
        @change="(next, sel) => updateBeatEdit(selected.t, next, sel)"
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
.tracks span, .muted { color: #666; font-size: 13px; }
.tracks .on { background: #dbeafe; border-color: #2563eb; }
.save { margin-left: auto; font-size: 13px; color: #15803d; }
.save.pending, .save.saving { color: #666; }
.save.unsaved { color: #b91c1c; font-weight: 600; }
.hint { color: #666; font-size: 13px; margin: 8px 0 0; }
</style>
