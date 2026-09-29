<script setup>
// Edit panel for one beat of one track (`score` is that track): the measure's source
// image, one fret box and a tie ("延音") toggle per string,
// duration / dot / triplet / rest, insert / delete / confirm, and the measure-fill check.
import { computed, ref, watch } from 'vue'
import { api } from '../api.js'
import { scoreTuning } from '../lib/alphatex.js'
import {
  MAX_FRET,
  confirmBeat,
  deleteBeat,
  fracCompare,
  insertBeat,
  measureFill,
  setDuration,
  setFret,
  toggleDot,
  toggleRest,
  toggleTie,
  toggleTriplet,
} from '../lib/scoreEdit.js'
import { measureSource } from '../lib/source.js'
import { midiToName } from '../lib/tuning.js'

const props = defineProps({
  job: { type: Object, required: true },
  score: { type: Object, required: true },
  m: { type: Number, required: true },
  b: { type: Number, required: true },
})
// change: (newScore, newSelection)
const emit = defineEmits(['change', 'close'])

const DURATIONS = [
  [1, '全'],
  [2, '2分'],
  [4, '4分'],
  [8, '8分'],
  [16, '16分'],
  [32, '32分'],
]
const CROP_WIDTH = 320 // px shown in the panel
const CROP_HEIGHT = 220 // max px
const PAD = 12 // source px kept on both sides of the measure

const measure = computed(() => props.score.measures[props.m])
const beat = computed(() => measure.value.beats[props.b] ?? null)
const invalid = ref({}) // string -> text the user typed that is not a fret

watch(
  () => [props.m, props.b],
  () => (invalid.value = {}),
)

// strings listed from the highest (top line of the tab) down
const strings = computed(() => {
  const tuning = scoreTuning(props.score)
  const out = []
  for (let s = props.score.strings - 1; s >= 0; s--) {
    const note = beat.value?.notes.find((n) => n.string === s)
    out.push({
      string: s,
      label: `${props.score.strings - s} 弦 ${midiToName(tuning[s])}`,
      value: note ? (note.dead ? 'x' : String(note.fret)) : '',
      low: note && note.confidence < 0.7,
      tied: !!note?.tied,
      canTie: !!note && !note.dead,
    })
  }
  return out
})

// ------------------------------------------------------------------ source image crop

const source = computed(() => measureSource(props.job, measure.value))
const pageUrl = computed(() =>
  source.value.kind === 'page' ? api.fileUrl(props.job.id, source.value.file) : '',
)
const natural = ref(null) // { w, h } of the page image
const broken = ref(false) // the page file is gone (pages re-analyzed after recognition)

watch(
  pageUrl,
  (url) => {
    natural.value = null
    broken.value = false
    if (!url) return
    const img = new Image()
    img.onload = () => {
      if (url === pageUrl.value) natural.value = { w: img.naturalWidth, h: img.naturalHeight }
    }
    img.onerror = () => {
      if (url === pageUrl.value) broken.value = true
    }
    img.src = url
  },
  { immediate: true },
)

const crop = computed(() => {
  if (!natural.value) return null
  const mm = measure.value
  const x0 = Math.max(0, mm.x0 - PAD)
  const x1 = Math.min(natural.value.w, Math.max(mm.x1, mm.x0 + 1) + PAD)
  const scale = Math.min(1.5, CROP_WIDTH / (x1 - x0), CROP_HEIGHT / natural.value.h)
  const marker = beat.value ? (beat.value.x - x0) * scale : null
  return {
    box: {
      width: `${(x1 - x0) * scale}px`,
      height: `${natural.value.h * scale}px`,
      backgroundImage: `url("${pageUrl.value}")`,
      backgroundSize: `${natural.value.w * scale}px auto`,
      backgroundPosition: `${-x0 * scale}px 0`,
    },
    marker: marker === null ? null : { left: `${marker}px` },
  }
})

// ------------------------------------------------------------------ edits

function change(score, sel = { m: props.m, b: props.b }) {
  emit('change', score, sel)
}

function onFret(string, event) {
  const text = event.target.value.trim()
  let value
  if (text === '') value = null
  else if (text.toLowerCase() === 'x') value = 'x'
  else if (/^\d+$/.test(text) && Number(text) <= MAX_FRET) value = Number(text)
  else {
    invalid.value = { ...invalid.value, [string]: text }
    return
  }
  const { [string]: _, ...rest } = invalid.value
  invalid.value = rest
  change(setFret(props.score, props.m, props.b, string, value))
}

function insert(where) {
  change(insertBeat(props.score, props.m, props.b, where), {
    m: props.m,
    b: where === 'before' ? props.b : props.b + 1,
  })
}

function remove() {
  const next = deleteBeat(props.score, props.m, props.b)
  change(next, { m: props.m, b: Math.min(props.b, next.measures[props.m].beats.length - 1) })
}

const fill = computed(() => {
  const { used, capacity } = measureFill(measure.value)
  const cmp = fracCompare(used, capacity)
  if (cmp === 0) return null
  const text = (f) => (f.d === 1 ? `${f.n}` : `${f.n}/${f.d}`)
  const what = cmp < 0 ? '没填满' : '超出了'
  return `本小节时值${what}拍号：共 ${text(used)} 个全音符，应为 ${text(capacity)}`
})
</script>

<template>
  <div class="card editor">
    <div class="row head">
      <!-- m + 1 is the bar number alphaTab draws; after padding it equals measure.number -->
      <strong>第 {{ m + 1 }} 小节 · 第 {{ b + 1 }} 拍</strong>
      <button class="close" title="关闭" @click="emit('close')">×</button>
    </div>
    <div v-if="crop" class="crop" :style="crop.box">
      <div v-if="crop.marker" class="marker" :style="crop.marker" />
    </div>
    <p v-else-if="source.kind === 'absent'" class="hint">视频中没有这一小节</p>
    <p v-else-if="broken || source.kind === 'missing'" class="hint">
      原图已更新，请重新识谱以对照
    </p>
    <p v-if="fill" class="warn">{{ fill }}</p>

    <template v-if="beat">
      <div class="frets">
        <label v-for="s in strings" :key="s.string" :class="{ low: s.low }">
          <span>{{ s.label }}</span>
          <input
            type="text"
            inputmode="numeric"
            maxlength="2"
            :data-string="s.string"
            :value="invalid[s.string] ?? s.value"
            :class="{ bad: s.string in invalid }"
            @change="onFret(s.string, $event)"
          />
          <button
            class="tie"
            :class="{ on: s.tied }"
            :disabled="!s.canTie"
            :data-tie="s.string"
            title="延音：与前一个同弦的音连起来（不重新拨弦）"
            @click.prevent="change(toggleTie(score, m, b, s.string))"
          >
            延音
          </button>
        </label>
      </div>
      <p v-if="Object.keys(invalid).length" class="error">品格应为 0–{{ MAX_FRET }}，或 x 表示闷音</p>
      <p class="hint">留空 = 没有音，x = 闷音；“延音”= 接着前一个同弦的音，不重新拨弦</p>

      <div class="row">
        <button
          v-for="[d, label] in DURATIONS"
          :key="d"
          :class="{ on: beat.duration === d }"
          @click="change(setDuration(score, m, b, d))"
        >
          {{ label }}
        </button>
      </div>
      <div class="row">
        <button :class="{ on: beat.dots }" @click="change(toggleDot(score, m, b))">附点</button>
        <button :class="{ on: beat.tuplet }" @click="change(toggleTriplet(score, m, b))">三连音</button>
        <button :class="{ on: beat.rest }" @click="change(toggleRest(score, m, b))">休止</button>
      </div>
      <div class="row">
        <button @click="insert('before')">前插一拍</button>
        <button @click="insert('after')">后插一拍</button>
        <button @click="remove">删除此拍</button>
        <button class="primary" @click="change(confirmBeat(score, m, b))">确认无误</button>
      </div>
    </template>
    <p v-else class="hint">这一小节没有拍</p>
  </div>
</template>

<style scoped>
.editor { width: 340px; box-sizing: border-box; }
.head { justify-content: space-between; margin-bottom: 8px; }
.close { padding: 2px 10px; }
.crop { position: relative; background-repeat: no-repeat; border: 1px solid #ddd; margin-bottom: 8px; }
.marker { position: absolute; top: 0; bottom: 0; width: 2px; background: rgba(37, 99, 235, 0.7); }
.frets { display: grid; grid-template-columns: 1fr; gap: 6px; margin-bottom: 4px; }
.frets label { display: flex; align-items: center; gap: 6px; font-size: 13px; }
.frets label span { flex: 1; }
.tie { padding: 1px 8px; font-size: 12px; }
.frets input { width: 44px; text-align: center; }
.frets .low span { background: rgba(245, 158, 11, 0.35); border-radius: 3px; padding: 0 3px; }
.bad { border-color: #b91c1c !important; background: #fee2e2; }
.row { margin-bottom: 8px; }
.on { background: #dbeafe; border-color: #2563eb; }
.hint { color: #666; font-size: 13px; margin: 4px 0 8px; }
</style>
