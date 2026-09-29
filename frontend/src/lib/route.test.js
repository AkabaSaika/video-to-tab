import { describe, expect, it } from 'vitest'
import { drumsHash, guitarHash, parseHash, pianoHash } from './route.js'

describe('hash routes', () => {
  it('reads the guitar page and its job', () => {
    expect(parseHash('')).toEqual({ page: 'guitar', job: null })
    expect(parseHash('#job=abc123')).toEqual({ page: 'guitar', job: 'abc123' })
    expect(parseHash('#whatever')).toEqual({ page: 'guitar', job: null })
  })

  it('reads the piano page and its job', () => {
    expect(parseHash('#/piano')).toEqual({ page: 'piano', job: null })
    expect(parseHash('#/piano?job=f00d')).toEqual({ page: 'piano', job: 'f00d' })
    expect(parseHash('#/piano?job=')).toEqual({ page: 'piano', job: null })
  })

  it('reads the drum page and its job', () => {
    expect(parseHash('#/drums')).toEqual({ page: 'drums', job: null })
    expect(parseHash('#/drums?job=beef')).toEqual({ page: 'drums', job: 'beef' })
    expect(parseHash('#/drums?job=')).toEqual({ page: 'drums', job: null })
    expect(drumsHash('beef')).toBe('#/drums?job=beef')
    expect(drumsHash(null)).toBe('#/drums')
    expect(parseHash(drumsHash('x2'))).toEqual({ page: 'drums', job: 'x2' })
  })

  it('writes hashes that read back the same', () => {
    expect(pianoHash('f00d')).toBe('#/piano?job=f00d')
    expect(pianoHash(null)).toBe('#/piano')
    expect(guitarHash('abc')).toBe('#job=abc')
    expect(guitarHash(null)).toBe('')
    expect(parseHash(pianoHash('x1'))).toEqual({ page: 'piano', job: 'x1' })
    expect(parseHash(guitarHash('x1'))).toEqual({ page: 'guitar', job: 'x1' })
  })
})
