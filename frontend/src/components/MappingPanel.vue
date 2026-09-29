<script setup>
import { computed, ref, watch } from 'vue'
import { drumsApi } from '../api.js'
import { mappingRows, withOverride, withPreset } from '../lib/drums.js'

const props = defineProps({ job: { type: Object, required: true } })
const emit = defineEmits(['update'])
const mapping = ref(null)
const saving = ref(false)
const error = ref('')

const rows = computed(() => (mapping.value ? mappingRows(mapping.value) : []))

async function load() {
  error.value = ''
  try {
    mapping.value = await drumsApi.getMapping(props.job.id)
  } catch (e) {
    error.value = e.message
  }
}

// read again when pages are read again or deleted (other positions may be in use)
watch(
  () => [props.job.id, props.job.pages.map((p) => `${p.id}:${p.attempts}:${p.ok}`).join()],
  load,
  { immediate: true },
)

async function save(next) {
  error.value = ''
  saving.value = true
  try {
    const res = await drumsApi.setMapping(props.job.id, next)
    mapping.value = res.mapping
    emit('update', res.job)
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <details class="card" open>
    <summary><strong>乐器对应</strong>（谱面位置 + 符头 → 鼓件，修改后立即重新生成）</summary>
    <p v-if="error" class="error">{{ error }}</p>
    <template v-if="mapping">
      <div class="row">
        <label>
          预设：
          <select
            :value="mapping.preset"
            :disabled="saving"
            @change="save(withPreset(mapping, $event.target.value))"
          >
            <option v-for="p in mapping.presets" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </label>
        <span class="meta">选预设会清除下面的单独修改</span>
      </div>
      <p v-if="!rows.length" class="meta">还没有识别出的音符。</p>
      <table v-else class="map">
        <thead>
          <tr><th>谱面位置</th><th>符头</th><th>音符数</th><th>鼓件</th><th /></tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.key" :class="{ changed: r.overridden }">
            <td>{{ r.where }}</td>
            <td>{{ r.head }}</td>
            <td>{{ r.count }}</td>
            <td>
              <select
                :value="r.gm"
                :disabled="saving"
                @change="save(withOverride(mapping, r.key, Number($event.target.value)))"
              >
                <option v-for="i in mapping.instruments" :key="i.gm" :value="i.gm">
                  {{ i.label }}（{{ i.name }}，GM {{ i.gm }}）
                </option>
              </select>
            </td>
            <td>
              <button
                v-if="r.overridden && r.preset !== null"
                :disabled="saving"
                @click="save(withOverride(mapping, r.key, r.preset))"
              >
                恢复预设
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </template>
    <p v-else-if="!error" class="meta">读取中…</p>
  </details>
</template>

<style scoped>
summary { cursor: pointer; }
.map { border-collapse: collapse; margin-top: 8px; }
.map th, .map td { padding: 4px 10px; border-bottom: 1px solid #eee; text-align: left; font-size: 14px; }
.map tr.changed td:first-child { box-shadow: inset 3px 0 0 #2563eb; }
.meta { color: #666; font-size: 13px; }
</style>
