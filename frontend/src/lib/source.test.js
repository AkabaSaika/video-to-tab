import { describe, expect, it } from 'vitest'
import { measureSource } from './source.js'

const job = {
  score_order: [4, 2],
  pages: [
    { id: 2, file: 'pages/b.png' },
    { id: 4, file: 'pages/a.png' },
  ],
}

describe('measureSource', () => {
  it('finds the page a measure was read from via score_order', () => {
    expect(measureSource(job, { line: 0 })).toEqual({ kind: 'page', file: 'pages/a.png' })
    expect(measureSource(job, { line: 1 })).toEqual({ kind: 'page', file: 'pages/b.png' })
  })

  it('reports measures that were never shown in the video', () => {
    expect(measureSource(job, { line: -1 })).toEqual({ kind: 'absent' })
  })

  it('reports a page that no longer exists', () => {
    expect(measureSource(job, { line: 5 })).toEqual({ kind: 'missing' })
    expect(measureSource({ ...job, pages: [] }, { line: 0 })).toEqual({ kind: 'missing' })
  })
})

describe('measureSource with recorded files', () => {
  it('uses the file recorded at recognition, not the current page list', () => {
    const reanalyzed = {
      score_order: [4, 2],
      score_files: ['pages/run1_004.png', 'pages/run1_002.png'],
      pages: [
        { id: 2, file: 'pages/run2_002.png' },
        { id: 4, file: 'pages/run2_004.png' },
      ],
    }
    expect(measureSource(reanalyzed, { line: 0 })).toEqual({
      kind: 'page',
      file: 'pages/run1_004.png',
    })
    expect(measureSource(reanalyzed, { line: 1 }).file).toBe('pages/run1_002.png')
    expect(measureSource(reanalyzed, { line: 2 })).toEqual({ kind: 'missing' })
    expect(measureSource(reanalyzed, { line: -1 })).toEqual({ kind: 'absent' })
  })
})
