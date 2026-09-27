<script setup>
import { computed, reactive, ref } from 'vue'
import { api } from '../api.js'
import { clampRoi, displayToVideo, normalizeRect, videoToDisplay } from '../lib/roi.js'

const props = defineProps({ job: { type: Object, required: true } })
const emit = defineEmits(['started'])

const roi = reactive({ ...props.job.region.roi })
const params = reactive({ fps: 5, diff_threshold: 0.15, min_duration: 0.8 })
const img = ref(null)
const scale = ref(1) // video px per display px
const drag = ref(null)
const error = ref('')
const lowConfidence = computed(() => props.job.region.confidence < 0.5)

const box = computed(() => {
  const r = drag.value ? drag.value.rect : videoToDisplay(roi, scale.value)
  return { left: `${r.x}px`, top: `${r.y}px`, width: `${r.w}px`, height: `${r.h}px` }
})

function onLoad() {
  scale.value = props.job.width / img.value.clientWidth
}

function point(event) {
  const rect = img.value.getBoundingClientRect()
  return [event.clientX - rect.left, event.clientY - rect.top]
}

function onDown(event) {
  const [x, y] = point(event)
  drag.value = { x0: x, y0: y, rect: { x, y, w: 0, h: 0 } }
}

function onMove(event) {
  if (!drag.value) return
  const [x, y] = point(event)
  drag.value.rect = normalizeRect(drag.value.x0, drag.value.y0, x, y)
}

function onUp() {
  if (!drag.value) return
  const r = drag.value.rect
  drag.value = null
  if (r.w < 5 || r.h < 5) return
  Object.assign(roi, clampRoi(displayToVideo(r, scale.value), props.job.width, props.job.height))
}

async function start() {
  error.value = ''
  try {
    emit('started', await api.setRegion(props.job.id, { ...roi, ...params }))
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <div class="card">
    <h2>2. 确认谱面区域</h2>
    <p v-if="lowConfidence" class="warn">没能可靠地自动找到谱面，请在图上拖拽框选 tab 区域。</p>
    <p v-else>已自动框出谱面区域（蓝框），如不准确可在图上重新拖拽框选。</p>
    <div class="stage" @mousedown.prevent="onDown" @mousemove="onMove" @mouseup="onUp" @mouseleave="onUp">
      <img ref="img" :src="api.fileUrl(job.id, 'frame.jpg')" draggable="false" @load="onLoad" />
      <div class="roi" :style="box" />
    </div>
    <div class="row">
      <label>x <input v-model.number="roi.x" type="number" /></label>
      <label>y <input v-model.number="roi.y" type="number" /></label>
      <label>宽 <input v-model.number="roi.w" type="number" /></label>
      <label>高 <input v-model.number="roi.h" type="number" /></label>
    </div>
    <details>
      <summary>高级参数</summary>
      <div class="row">
        <label>采样 fps <input v-model.number="params.fps" type="number" step="1" min="1" /></label>
        <label>换页阈值 <input v-model.number="params.diff_threshold" type="number" step="0.01" /></label>
        <label>最短页时长(秒) <input v-model.number="params.min_duration" type="number" step="0.1" /></label>
      </div>
    </details>
    <p><button class="primary" @click="start">开始识别</button></p>
    <p v-if="error" class="error">{{ error }}</p>
  </div>
</template>

<style scoped>
.stage { position: relative; display: inline-block; cursor: crosshair; user-select: none; max-width: 100%; }
.stage img { display: block; max-width: 100%; }
.roi { position: absolute; border: 2px solid #2563eb; background: rgba(37, 99, 235, 0.12); pointer-events: none; }
label input { width: 80px; }
</style>
