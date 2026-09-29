<script setup>
// alphaTab wrapper: renders a Score, marks beats that need review and the selected beat,
// and reports clicks as { m, b } (measure and beat indices of the Score).
import * as alphaTab from '@coderline/alphatab'
import bravuraWoff from '@coderline/alphatab/font/Bravura.woff?url'
import bravuraWoff2 from '@coderline/alphatab/font/Bravura.woff2?url'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { scoreToTex } from '../lib/alphatex.js'
import { needsReview } from '../lib/scoreEdit.js'

const props = defineProps({
  score: { type: Object, required: true },
  selected: { type: Object, default: null },
})
const emit = defineEmits(['select', 'error', 'rendered'])

const wrap = ref(null)
const host = ref(null)
const boxes = shallowRef(new Map()) // "m:b" -> { left, top, width, height } in px
const rendering = ref(true)
let api = null

function key(m, b) {
  return `${m}:${b}`
}

function style(box) {
  return { left: `${box.x}px`, top: `${box.y}px`, width: `${box.w}px`, height: `${box.h}px` }
}

const flagged = computed(() => {
  const out = []
  props.score.measures.forEach((measure, m) =>
    measure.beats.forEach((beat, b) => {
      const box = boxes.value.get(key(m, b))
      if (box && needsReview(measure, beat)) out.push({ id: key(m, b), style: style(box) })
    }),
  )
  return out
})

const selectedBox = computed(() => {
  const box = props.selected && boxes.value.get(key(props.selected.m, props.selected.b))
  return box ? style(box) : null
})

// Beat columns in wrapper coordinates: x/width from the beat, y/height from its bar.
function collectBounds() {
  const lookup = api.renderer.boundsLookup
  const surface = host.value.querySelector('.at-surface')
  if (!lookup || !surface || !api.score) return
  const inner = surface.getBoundingClientRect()
  const outer = wrap.value.getBoundingClientRect()
  const dx = inner.left - outer.left
  const dy = inner.top - outer.top
  const map = new Map()
  api.score.tracks[0].staves[0].bars.forEach((bar, m) =>
    bar.voices[0].beats.forEach((beat, i) => {
      const bounds = lookup.findBeat(beat)
      if (!bounds) return
      const r = bounds.realBounds
      const col = bounds.barBounds.realBounds
      map.set(key(m, i), { x: r.x + dx, y: col.y + dy, w: r.w, h: col.h })
    }),
  )
  boxes.value = map
}

function render() {
  rendering.value = true
  try {
    api.tex(scoreToTex(props.score))
  } catch (e) {
    rendering.value = false
    emit('error', e.message)
  }
}

onMounted(() => {
  api = new alphaTab.AlphaTabApi(host.value, {
    core: {
      useWorkers: false, // only rendering, no playback: keep everything on the main thread
      enableLazyLoading: false, // all beats need bounds for the overlays
      smuflFontSources: new Map([
        ['woff2', bravuraWoff2],
        ['woff', bravuraWoff],
      ]),
    },
    // no playback; ScrollMode.Off stops alphaTab scrolling the page to the top on re-render
    player: { playerMode: alphaTab.PlayerMode.Disabled, scrollMode: alphaTab.ScrollMode.Off },
  })
  api.postRenderFinished.on(() => {
    collectBounds()
    rendering.value = false
    emit('rendered')
  })
  api.beatMouseDown.on((beat) => emit('select', { m: beat.voice.bar.index, b: beat.index }))
  api.error.on((e) => {
    rendering.value = false
    emit('error', e?.message || String(e))
  })
  render()
})

onBeforeUnmount(() => api?.destroy())

watch(() => props.score, render)

// keep the selected beat in view (e.g. after "下一个待检查")
watch(
  () => props.selected,
  async () => {
    await nextTick()
    wrap.value?.querySelector('.sel')?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  },
)

function exportGp() {
  if (!api?.score) throw new Error('谱面尚未渲染完成')
  return new alphaTab.exporter.Gp7Exporter().export(api.score, api.settings)
}

defineExpose({ exportGp })
</script>

<template>
  <div ref="wrap" class="tab-wrap">
    <div ref="host" class="tab-host" />
    <div class="layer">
      <div v-for="f in flagged" :key="f.id" class="flag" :style="f.style" />
      <div v-if="selectedBox" class="sel" :style="selectedBox" />
    </div>
    <p v-if="rendering" class="busy">正在渲染谱面…</p>
  </div>
</template>

<style scoped>
.tab-wrap { position: relative; min-height: 120px; }
.layer { position: absolute; inset: 0; pointer-events: none; }
.flag { position: absolute; background: rgba(245, 158, 11, 0.28); border-radius: 3px; }
.sel { position: absolute; border: 2px solid #2563eb; border-radius: 3px; background: rgba(37, 99, 235, 0.1); }
.busy { position: absolute; top: 0; right: 0; margin: 0; font-size: 13px; color: #666; }
</style>
