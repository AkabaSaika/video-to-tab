import { afterEach, describe, expect, it, vi } from 'vitest'
import { pianoApi } from '../api.js'
import { exportName, progressText, rowState, withoutSystem } from './piano.js'

const job = {
  id: 'j1',
  status: 'ready',
  systems: [
    { id: 0, image: 'systems/000.png', musicxml: 'systems/000.musicxml', ok: true, error: null },
    { id: 1, image: 'systems/001.png', musicxml: null, ok: false, error: '没有识别出乐谱' },
    { id: 2, image: 'systems/002.png', musicxml: null, ok: null, error: null },
  ],
}

describe('result list state', () => {
  it('labels each system row', () => {
    expect(rowState(job.systems[0])).toEqual({ kind: 'ok', label: '' })
    expect(rowState(job.systems[1])).toEqual({ kind: 'failed', label: '识别失败：没有识别出乐谱' })
    expect(rowState(job.systems[2])).toEqual({ kind: 'pending', label: '等待识别' })
  })

  it('shows the three stages, with k / n while recognizing', () => {
    expect(progressText({ status: 'downloading', stage: 'download', systems: [] })).toBe('下载视频…')
    expect(progressText({ status: 'capturing', stage: 'capture', systems: [] })).toBe('截取谱表…')
    expect(progressText({ ...job, status: 'recognizing', stage: 'recognize' })).toBe(
      '识别中：第 3 / 3 组', // two done, the third in progress
    )
  })

  it('drops a deleted system without touching the others', () => {
    const next = withoutSystem(job, 1)
    expect(next.systems.map((s) => s.id)).toEqual([0, 2])
    expect(job.systems).toHaveLength(3)
  })

  it('names the export after the job', () => {
    expect(exportName({ id: 'j1', title: 'Für Elise' })).toBe('Für Elise.musicxml')
    expect(exportName({ id: 'j1', title: '' })).toBe('piano-j1.musicxml')
  })
})

describe('piano api calls', () => {
  afterEach(() => vi.unstubAllGlobals())

  function stubFetch(body = {}, ok = true) {
    const fetch = vi.fn().mockResolvedValue({ ok, status: ok ? 200 : 409, json: async () => body })
    vi.stubGlobal('fetch', fetch)
    return fetch
  }

  it('deletes one system', async () => {
    const fetch = stubFetch(job)
    expect(await pianoApi.deleteSystem('j1', 1)).toEqual(job)
    expect(fetch).toHaveBeenCalledWith('/api/piano/jobs/j1/systems/1', { method: 'DELETE' })
  })

  it('re-recognizes one system', async () => {
    const fetch = stubFetch(job)
    await pianoApi.recognizeSystem('j1', 2)
    expect(fetch).toHaveBeenCalledWith('/api/piano/jobs/j1/systems/2/recognize', {
      method: 'POST',
    })
  })

  it('surfaces the server message on errors', async () => {
    stubFetch({ detail: '任务正在处理中，请稍后再试' }, false)
    await expect(pianoApi.recognizeSystem('j1', 2)).rejects.toThrow('任务正在处理中')
  })

  it('creates jobs, lists them and builds file urls', async () => {
    const fetch = stubFetch([])
    await pianoApi.createFromUrl('BV1xx411c7mD')
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/piano/jobs')
    expect(init.method).toBe('POST')
    expect(init.body.get('url')).toBe('BV1xx411c7mD')
    await pianoApi.listJobs()
    expect(fetch.mock.calls[1]).toEqual(['/api/piano/jobs', { method: 'GET' }])
    expect(pianoApi.fileUrl('j1', 'systems/000.png')).toBe('/api/piano/jobs/j1/files/systems/000.png')
    expect(pianoApi.musicxmlUrl('j1')).toBe('/api/piano/jobs/j1/musicxml')
  })
})
