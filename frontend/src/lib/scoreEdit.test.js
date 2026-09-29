import { describe, expect, it } from 'vitest'
import {
  beatLength,
  confirmBeat,
  deleteBeat,
  insertBeat,
  measureFill,
  needsReview,
  nextToReview,
  setDuration,
  setFret,
  toggleDot,
  toggleRest,
  toggleTriplet,
} from './scoreEdit.js'

const note = (string, fret, confidence = 1) => ({ string, fret, confidence, dead: false })
const beat = (notes, extra = {}) => ({
  duration: 4,
  dots: 0,
  tuplet: null,
  rest: notes.length === 0,
  notes,
  x: 10,
  confidence: 1,
  ...extra,
})
const measure = (beats, extra = {}) => ({
  number: 1,
  time: [4, 4],
  beats,
  line: 0,
  x0: 0,
  x1: 100,
  confidence: 1,
  ...extra,
})

function sample() {
  return {
    strings: 6,
    tuning: [40, 45, 50, 55, 59, 64],
    tempo: null,
    title: '',
    measures: [
      measure([beat([note(0, 3)]), beat([note(1, 5), note(2, 7)]), beat([]), beat([note(0, 1)])]),
      measure([beat([note(0, 3, 0.5)], { duration: 2 }), beat([note(1, 2)], { duration: 2 })]),
      measure([beat([note(0, 3)], { duration: 1 })], { confidence: 0.3 }),
    ],
  }
}

// every edit must leave the input untouched
function frozen() {
  const s = sample()
  const deepFreeze = (o) => {
    Object.values(o).forEach((v) => v && typeof v === 'object' && deepFreeze(v))
    return Object.freeze(o)
  }
  return deepFreeze(s)
}

describe('scoreEdit', () => {
  it('setFret adds, changes, mutes and removes notes', () => {
    const s = frozen()
    let t = setFret(s, 0, 1, 4, 12)
    expect(t.measures[0].beats[1].notes.map((n) => [n.string, n.fret])).toEqual([
      [1, 5],
      [2, 7],
      [4, 12],
    ])
    t = setFret(t, 0, 1, 2, 9)
    expect(t.measures[0].beats[1].notes[1]).toEqual({ string: 2, fret: 9, confidence: 1, dead: false })
    t = setFret(t, 0, 1, 1, 'x')
    expect(t.measures[0].beats[1].notes[0]).toEqual({ string: 1, fret: 0, confidence: 1, dead: true })
    t = setFret(s, 0, 0, 0, null)
    expect(t.measures[0].beats[0]).toMatchObject({ notes: [], rest: true })
    t = setFret(s, 0, 2, 3, 0)
    expect(t.measures[0].beats[2]).toMatchObject({ notes: [note(3, 0)], rest: false })
    expect(s).toEqual(sample())
  })

  it('setFret rejects frets outside 0..30', () => {
    const s = frozen()
    for (const bad of [-1, 31, 2.5, NaN]) expect(() => setFret(s, 0, 0, 0, bad)).toThrow('品格')
    expect(setFret(s, 0, 0, 0, 30).measures[0].beats[0].notes[0].fret).toBe(30)
  })

  it('changes duration, dot, triplet and rest', () => {
    const s = frozen()
    expect(setDuration(s, 0, 0, 16).measures[0].beats[0].duration).toBe(16)
    expect(() => setDuration(s, 0, 0, 3)).toThrow()
    const dotted = toggleDot(s, 0, 0)
    expect(dotted.measures[0].beats[0].dots).toBe(1)
    expect(toggleDot(dotted, 0, 0).measures[0].beats[0].dots).toBe(0)
    const trip = toggleTriplet(s, 0, 0)
    expect(trip.measures[0].beats[0].tuplet).toBe(3)
    expect(toggleTriplet(trip, 0, 0).measures[0].beats[0].tuplet).toBeNull()
    const rest = toggleRest(s, 0, 1)
    expect(rest.measures[0].beats[1]).toMatchObject({ rest: true, notes: [] })
    expect(toggleRest(rest, 0, 1).measures[0].beats[1].rest).toBe(false)
    expect(s).toEqual(sample())
  })

  it('inserts a rest beat before or after', () => {
    const s = frozen()
    const before = insertBeat(s, 1, 1, 'before')
    expect(before.measures[1].beats).toHaveLength(3)
    expect(before.measures[1].beats[1]).toMatchObject({ rest: true, notes: [], duration: 2 })
    expect(before.measures[1].beats[2]).toBe(s.measures[1].beats[1])
    const after = insertBeat(s, 1, 1, 'after')
    expect(after.measures[1].beats[2]).toMatchObject({ rest: true, duration: 2 })
    expect(after.measures[0]).toBe(s.measures[0]) // untouched measures are shared
    expect(s).toEqual(sample())
  })

  it('deletes a beat; the last one becomes a whole rest', () => {
    const s = frozen()
    const t = deleteBeat(s, 0, 1)
    expect(t.measures[0].beats.map((b) => b.notes.length)).toEqual([1, 0, 1])
    const u = deleteBeat(s, 2, 0)
    expect(u.measures[2].beats).toEqual([
      { duration: 1, dots: 0, tuplet: null, rest: true, notes: [], x: 50, confidence: 1 },
    ])
    expect(s).toEqual(sample())
  })

  it('confirmBeat sets the beat and note confidence to 1', () => {
    const s = frozen()
    const t = confirmBeat(s, 1, 0)
    expect(t.measures[1].beats[0].confidence).toBe(1)
    expect(t.measures[1].beats[0].notes[0].confidence).toBe(1)
    expect(needsReview(t.measures[1], t.measures[1].beats[0])).toBe(false)
    // a measure that adds up is checked too; one that does not stays flagged
    expect(confirmBeat(s, 2, 0).measures[2].confidence).toBe(1)
    const short = setDuration(s, 2, 0, 2)
    expect(confirmBeat(short, 2, 0).measures[2].confidence).toBe(0.3)
    expect(s).toEqual(sample())
  })

  it('measureFill adds beat lengths as fractions', () => {
    expect(beatLength(beat([], { duration: 8, dots: 1 }))).toEqual({ n: 3, d: 16 })
    expect(beatLength(beat([], { duration: 8, tuplet: 3 }))).toEqual({ n: 1, d: 12 })
    expect(beatLength(beat([], { duration: 4, dots: 2 }))).toEqual({ n: 7, d: 16 })
    const full = measureFill(sample().measures[0])
    expect(full).toEqual({ used: { n: 1, d: 1 }, capacity: { n: 1, d: 1 } })
    const trip = measure([
      ...[0, 1, 2].map(() => beat([], { duration: 8, tuplet: 3 })),
      beat([], { duration: 4 }),
      beat([], { duration: 2 }),
    ])
    expect(measureFill(trip).used).toEqual({ n: 1, d: 1 })
    expect(measureFill(measure([beat([])])).used).toEqual({ n: 1, d: 4 })
    expect(measureFill(measure([], { time: [3, 4] })).capacity).toEqual({ n: 3, d: 4 })
  })

  it('needsReview flags low beat, note or measure confidence', () => {
    const m = measure([])
    expect(needsReview(m, beat([note(0, 1)]))).toBe(false)
    expect(needsReview(m, beat([note(0, 1)], { confidence: 0.69 }))).toBe(true)
    expect(needsReview(m, beat([note(0, 1, 0.6)]))).toBe(true)
    expect(needsReview(m, beat([note(0, 1, 0.7)]))).toBe(false)
    expect(needsReview(measure([], { confidence: 0.99 }), beat([]))).toBe(true)
  })

  it('nextToReview walks the flagged beats in order and wraps around', () => {
    const s = sample()
    expect(nextToReview(s, null)).toEqual({ m: 1, b: 0 })
    expect(nextToReview(s, { m: 1, b: 0 })).toEqual({ m: 2, b: 0 })
    expect(nextToReview(s, { m: 2, b: 0 })).toEqual({ m: 1, b: 0 })
    expect(nextToReview(s, { m: 0, b: 3 })).toEqual({ m: 1, b: 0 })
    const clean = confirmBeat(confirmBeat(s, 1, 0), 2, 0)
    expect(nextToReview(clean, null)).toBeNull()
  })
})
