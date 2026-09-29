// Drum page state and the instrument-mapping panel's logic, kept free of Vue so it can be
// tested in Node.

export const BUSY = ['downloading', 'capturing', 'recognizing']

export const STATUS = {
  downloading: '下载中',
  capturing: '截取谱面中',
  recognizing: '识别中',
  ready: '已完成',
  failed: '失败',
}

export const TIMES = ['2/4', '3/4', '4/4', '5/4', '6/8', '7/8', '9/8', '12/8', '2/2', '3/8']

export function rowState(page) {
  if (page.ok === true) {
    const label = page.measures
      ? `${page.measures} 小节（${page.summed ?? 0} 小节时值对齐）`
      : ''
    return { kind: 'ok', label }
  }
  if (page.ok === false) return { kind: 'failed', label: `识别失败：${page.error || '未知错误'}` }
  return { kind: 'pending', label: '等待识别' }
}

export function progressText(job) {
  if (job.status === 'downloading') return '下载视频…'
  if (job.status === 'capturing') return '截取谱面…'
  if (job.status === 'recognizing') {
    const n = job.pages.length
    const done = job.pages.filter((p) => p.ok !== null && p.ok !== undefined).length
    return `识别中：第 ${Math.min(done + 1, n)} / ${n} 页`
  }
  return '处理中…'
}

export function withoutPage(job, pid) {
  return { ...job, pages: job.pages.filter((p) => p.id !== pid) }
}

export function exportName(job, ext) {
  return `${job.title || `drums-${job.id}`}.${ext}`
}

export function timeText(job) {
  if (job.time) return job.time.join('/')
  if (job.detected_time) return `${job.detected_time.join('/')}（识别）`
  return '4/4（默认）'
}

// The body of PUT /settings: 'auto' keeps the time signature read from the video.
export function settingsBody(time, tempo) {
  const bpm = Number(tempo)
  if (!Number.isInteger(bpm) || bpm < 20 || bpm > 400) throw new Error('速度应为 20–400 之间的整数')
  return { time: time === 'auto' ? null : time.split('/').map(Number), tempo: bpm }
}

// Staff positions on a percussion staff, bottom line E4 = 第一线.
const STEPS = 'CDEFGAB'
const PLACES = [
  [-4, '下加二线'],
  [-3, '下加一线下方'],
  [-2, '下加一线'],
  [-1, '下加一间'],
  [0, '第一线'],
  [1, '第一间'],
  [2, '第二线'],
  [3, '第二间'],
  [4, '第三线'],
  [5, '第三间'],
  [6, '第四线'],
  [7, '第四间'],
  [8, '第五线'],
  [9, '上加一间'],
  [10, '上加一线'],
  [11, '上加一线上方'],
  [12, '上加二线'],
]

export function positionLabel(pos) {
  const step = STEPS.indexOf(pos[0]) + 7 * Number(pos.slice(1)) - (2 + 7 * 4)
  const place = PLACES.find(([s]) => s === step)
  return place ? place[1] : pos
}

export function headLabel(head) {
  return { normal: '普通符头', x: '×', 'circle-x': '圈×' }[head] || head
}

function presetTable(mapping, id = mapping.preset) {
  return (mapping.presets.find((p) => p.id === id) || { table: {} }).table
}

// One row per (position, notehead) the recognized pages use, most used first.
export function mappingRows(mapping) {
  const table = presetTable(mapping)
  return mapping.used.map((u) => {
    const [pos, head, open] = u.key.split(':')
    return {
      key: u.key,
      where: `${pos} ${positionLabel(pos)}`,
      head: headLabel(head) + (open ? ' + o（开）' : ''),
      count: u.count,
      gm: u.gm,
      overridden: Boolean(u.overridden),
      preset: table[u.key] ?? null,
    }
  })
}

// The mapping with one position set to `gm`; choosing the preset's own drum removes the
// override. Never changes `mapping` itself.
export function withOverride(mapping, key, gm) {
  const overrides = { ...mapping.overrides }
  if (presetTable(mapping)[key] === gm) delete overrides[key]
  else overrides[key] = gm
  return { preset: mapping.preset, overrides }
}

export function withPreset(mapping, preset) {
  return { preset, overrides: {} }
}
