import { describe, expect, it } from 'vitest'
import { nextInSong } from './scoreEdit.js'
import { setTrack, toSong } from './song.js'

const score = { strings: 6, tuning: [40, 45, 50, 55, 59, 64], tempo: 150, title: 'Old', measures: [] }

describe('toSong', () => {
  it('wraps a single Score (score.json from before multi-track) into a one-track song', () => {
    const song = toSong(score)
    expect(song.title).toBe('Old')
    expect(song.tempo).toBe(150)
    expect(song.tracks).toHaveLength(1)
    expect(song.tracks[0]).toMatchObject({ strings: 6, tuning: score.tuning, measures: [], name: 'Guitar' })
  })

  it('leaves a song alone', () => {
    const song = { title: 't', tempo: null, tracks: [{ ...score, name: 'Gt.1' }] }
    expect(toSong(song)).toBe(song)
  })
})

describe('setTrack', () => {
  it('replaces one track and shares the others', () => {
    const song = { title: '', tempo: null, tracks: [{ name: 'a' }, { name: 'b' }] }
    const next = setTrack(song, 1, { name: 'c' })
    expect(next.tracks.map((t) => t.name)).toEqual(['a', 'c'])
    expect(next.tracks[0]).toBe(song.tracks[0])
    expect(song.tracks[1].name).toBe('b')
  })
})

describe('nextInSong', () => {
  const beat = (confidence) => ({ duration: 4, notes: [], confidence })
  const track = (...confs) => ({ measures: [{ confidence: 1, beats: confs.map(beat) }] })
  const song = { tracks: [track(1, 0.5), track(0.2, 1, 0.3)] }

  it('walks the flagged beats track by track and wraps around', () => {
    expect(nextInSong(song, null)).toEqual({ t: 0, m: 0, b: 1 })
    expect(nextInSong(song, { t: 0, m: 0, b: 1 })).toEqual({ t: 1, m: 0, b: 0 })
    expect(nextInSong(song, { t: 1, m: 0, b: 0 })).toEqual({ t: 1, m: 0, b: 2 })
    expect(nextInSong(song, { t: 1, m: 0, b: 2 })).toEqual({ t: 0, m: 0, b: 1 })
    expect(nextInSong({ tracks: [track(1)] }, null)).toBeNull()
  })
})
