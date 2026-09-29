import { afterEach, describe, expect, it, vi } from 'vitest'
import { drumsApi } from '../api.js'
import {
  TIMES,
  exportName,
  headLabel,
  mappingRows,
  positionLabel,
  progressText,
  rowState,
  settingsBody,
  timeText,
  withOverride,
  withPreset,
  withoutPage,
} from './drums.js'

const job = {
  id: 'd1',
  title: '',
  status: 'ready',
  time: null,
  detected_time: [4, 4],
  tempo: 120,
  pages: [
    { id: 0, image: 'pages/000.png', musicxml: 'pages/000.musicxml', ok: true, measures: 4, summed: 3 },
    { id: 1, image: 'pages/001.png', musicxml: null, ok: false, error: '这一页没有识别出小节' },
    { id: 2, image: 'pages/002.png', musicxml: null, ok: null },
  ],
}

const mapping = {
  preset: 'default',
  overrides: { 'C5:normal': 40 },
  table: { 'C5:normal': 40, 'G5:x': 42, 'G5:x:open': 46, 'F4:normal': 36 },
  presets: [
    { id: 'default', name: '通用', table: { 'C5:normal': 38, 'G5:x': 42, 'G5:x:open': 46, 'F4:normal': 36 } },
    { id: 'gp', name: 'Guitar Pro', table: { 'C5:normal': 38, 'G5:x': 42, 'F4:normal': 36 } },
  ],
  instruments: [
    { gm: 36, name: 'Bass Drum 1', label: '底鼓' },
    { gm: 38, name: 'Acoustic Snare', label: '军鼓' },
    { gm: 40, name: 'Electric Snare', label: '军鼓 2' },
    { gm: 42, name: 'Closed Hi-Hat', label: '闭镲' },
    { gm: 46, name: 'Open Hi-Hat', label: '开镲' },
  ],
  used: [
    { key: 'G5:x', count: 30, gm: 42, overridden: false },
    { key: 'C5:normal', count: 8, gm: 40, overridden: true },
    { key: 'F4:normal', count: 8, gm: 36, overridden: false },
    { key: 'G5:x:open', count: 2, gm: 46, overridden: false },
  ],
}

describe('drum page state', () => {
  it('labels each page row', () => {
    expect(rowState(job.pages[0])).toEqual({ kind: 'ok', label: '4 小节（3 小节时值对齐）' })
    expect(rowState(job.pages[1])).toEqual({ kind: 'failed', label: '识别失败：这一页没有识别出小节' })
    expect(rowState(job.pages[2])).toEqual({ kind: 'pending', label: '等待识别' })
  })

  it('shows the three stages, with k / n while recognizing', () => {
    expect(progressText({ status: 'downloading', pages: [] })).toBe('下载视频…')
    expect(progressText({ status: 'capturing', pages: [] })).toBe('截取谱面…')
    expect(progressText({ ...job, status: 'recognizing' })).toBe('识别中：第 3 / 3 页')
  })

  it('drops a deleted page without touching the others', () => {
    expect(withoutPage(job, 1).pages.map((p) => p.id)).toEqual([0, 2])
    expect(job.pages).toHaveLength(3)
  })

  it('names the exports after the job', () => {
    expect(exportName({ id: 'd1', title: 'The Middle' }, 'mid')).toBe('The Middle.mid')
    expect(exportName({ id: 'd1', title: '' }, 'musicxml')).toBe('drums-d1.musicxml')
  })

  it('shows and sets the time signature and tempo', () => {
    expect(timeText(job)).toBe('4/4（识别）')
    expect(timeText({ ...job, detected_time: null })).toBe('4/4（默认）')
    expect(timeText({ ...job, time: [6, 8] })).toBe('6/8')
    expect(TIMES).toContain('12/8')
    expect(settingsBody('auto', '96')).toEqual({ time: null, tempo: 96 })
    expect(settingsBody('3/4', 100)).toEqual({ time: [3, 4], tempo: 100 })
    expect(() => settingsBody('3/4', 'x')).toThrow('速度')
  })
})

describe('instrument mapping panel', () => {
  it('names positions and noteheads in Chinese', () => {
    expect(positionLabel('F4')).toBe('第一间')
    expect(positionLabel('G5')).toBe('上加一间')
    expect(positionLabel('D4')).toBe('下加一间')
    expect(headLabel('x')).toBe('×')
    expect(headLabel('circle-x')).toBe('圈×')
    expect(headLabel('normal')).toBe('普通符头')
  })

  it('lists every used position with its drum', () => {
    const rows = mappingRows(mapping)
    expect(rows.map((r) => r.key)).toEqual(['G5:x', 'C5:normal', 'F4:normal', 'G5:x:open'])
    expect(rows[0]).toMatchObject({ where: 'G5 上加一间', head: '×', count: 30, gm: 42 })
    expect(rows[1]).toMatchObject({ gm: 40, overridden: true, preset: 38 })
    expect(rows[3].head).toBe('× + o（开）')
  })

  it('overrides one position, and going back to the preset removes the override', () => {
    const a = withOverride(mapping, 'F4:normal', 35)
    expect(a).toEqual({ preset: 'default', overrides: { 'C5:normal': 40, 'F4:normal': 35 } })
    const b = withOverride(mapping, 'C5:normal', 38) // the preset's own drum
    expect(b).toEqual({ preset: 'default', overrides: {} })
    expect(mapping.overrides).toEqual({ 'C5:normal': 40 }) // not changed in place
  })

  it('switching presets starts from that preset', () => {
    expect(withPreset(mapping, 'gp')).toEqual({ preset: 'gp', overrides: {} })
  })
})

describe('drum api calls', () => {
  afterEach(() => vi.unstubAllGlobals())

  function stubFetch(body = {}, ok = true) {
    const fetch = vi.fn().mockResolvedValue({ ok, status: ok ? 200 : 409, json: async () => body })
    vi.stubGlobal('fetch', fetch)
    return fetch
  }

  it('creates, lists and reads jobs', async () => {
    const fetch = stubFetch([])
    await drumsApi.createFromUrl('https://youtu.be/Pxt93gz8jas')
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/drums/jobs')
    expect(init.body.get('url')).toBe('https://youtu.be/Pxt93gz8jas')
    await drumsApi.listJobs()
    expect(fetch.mock.calls[1]).toEqual(['/api/drums/jobs', { method: 'GET' }])
    await drumsApi.getJob('d1')
    expect(fetch.mock.calls[2]).toEqual(['/api/drums/jobs/d1', { method: 'GET' }])
  })

  it('deletes and re-recognizes one page', async () => {
    const fetch = stubFetch(job)
    await drumsApi.deletePage('d1', 1)
    expect(fetch).toHaveBeenCalledWith('/api/drums/jobs/d1/pages/1', { method: 'DELETE' })
    await drumsApi.recognizePage('d1', 2)
    expect(fetch).toHaveBeenCalledWith('/api/drums/jobs/d1/pages/2/recognize', { method: 'POST' })
  })

  it('reads and writes the mapping and the settings', async () => {
    const fetch = stubFetch(mapping)
    await drumsApi.getMapping('d1')
    expect(fetch.mock.calls[0]).toEqual(['/api/drums/jobs/d1/mapping', { method: 'GET' }])
    await drumsApi.setMapping('d1', { preset: 'gp', overrides: { 'C5:normal': 40 } })
    const [url, init] = fetch.mock.calls[1]
    expect(url).toBe('/api/drums/jobs/d1/mapping')
    expect(init.method).toBe('PUT')
    expect(JSON.parse(init.body)).toEqual({ preset: 'gp', overrides: { 'C5:normal': 40 } })
    await drumsApi.setSettings('d1', { time: [3, 4], tempo: 90 })
    expect(fetch.mock.calls[2][0]).toBe('/api/drums/jobs/d1/settings')
    expect(JSON.parse(fetch.mock.calls[2][1].body)).toEqual({ time: [3, 4], tempo: 90 })
  })

  it('surfaces the server message on errors, builds file and export urls', async () => {
    stubFetch({ detail: '任务正在处理中，请稍后再试' }, false)
    await expect(drumsApi.recognizePage('d1', 2)).rejects.toThrow('任务正在处理中')
    expect(drumsApi.fileUrl('d1', 'pages/000.png')).toBe('/api/drums/jobs/d1/files/pages/000.png')
    expect(drumsApi.musicxmlUrl('d1')).toBe('/api/drums/jobs/d1/musicxml')
    expect(drumsApi.midiUrl('d1')).toBe('/api/drums/jobs/d1/midi')
  })
})
