// Piano result page state, kept free of Vue so it can be tested in Node.

export const BUSY = ['downloading', 'capturing', 'recognizing']

export const STATUS = {
  downloading: '下载中',
  capturing: '截取谱表中',
  recognizing: '识别中',
  ready: '已完成',
  failed: '失败',
}

export function rowState(system) {
  if (system.ok === true) return { kind: 'ok', label: '' }
  if (system.ok === false) return { kind: 'failed', label: `识别失败：${system.error || '未知错误'}` }
  return { kind: 'pending', label: '等待识别' }
}

export function progressText(job) {
  if (job.status === 'downloading') return '下载视频…'
  if (job.status === 'capturing') return '截取谱表…'
  if (job.status === 'recognizing') {
    const n = job.systems.length
    const done = job.systems.filter((s) => s.ok !== null && s.ok !== undefined).length
    return `识别中：第 ${Math.min(done + 1, n)} / ${n} 组`
  }
  return '处理中…'
}

export function withoutSystem(job, sid) {
  return { ...job, systems: job.systems.filter((s) => s.id !== sid) }
}

export function exportName(job) {
  return `${job.title || `piano-${job.id}`}.musicxml`
}
