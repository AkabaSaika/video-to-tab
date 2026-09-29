// Round trip in Node: Score -> alphaTex -> alphaTab -> Gp7Exporter bytes -> ScoreLoader.
import * as alphaTab from '@coderline/alphatab'
import { describe, expect, it } from 'vitest'
import { scoreToTex } from './alphatex.js'

const note = (string, fret, dead = false) => ({ string, fret, confidence: 1, dead })
const beat = (notes, duration, extra = {}) => ({
  duration,
  dots: 0,
  tuplet: null,
  rest: notes.length === 0,
  notes,
  x: 0,
  confidence: 1,
  ...extra,
})
const measure = (beats) => ({ number: 1, time: [4, 4], beats, line: 0, x0: 0, x1: 0, confidence: 1 })

const SCORE = {
  strings: 7,
  tuning: [33, 40, 45, 50, 55, 59, 64],
  tempo: 200,
  title: 'KiLLKiSS 测试',
  measures: [
    measure([
      beat([note(0, 7), note(1, 7)], 4),
      beat([note(0, 7), note(1, 7)], 8),
      beat([note(0, 0, true)], 8),
      beat([], 4),
      beat([note(0, 5)], 8, { dots: 1 }),
      beat([note(0, 5)], 16),
    ]),
    measure([
      beat([note(0, 3)], 8, { tuplet: 3 }),
      beat([note(0, 3)], 8, { tuplet: 3 }),
      beat([note(6, 3)], 8, { tuplet: 3 }),
      beat([note(2, 12), note(5, 15)], 4),
      beat([], 2),
    ]),
    measure([]),
  ],
}

// alphaTab's model numbers strings from the lowest, starting at 1
function summary(score) {
  const bars = score.tracks[0].staves[0].bars
  return bars.map((bar) =>
    bar.voices[0].beats.map((b) => ({
      duration: b.duration,
      dots: b.dots,
      tuplet: b.tupletNumerator > 0 ? b.tupletNumerator : null,
      rest: b.isRest,
      notes: b.notes.map((n) => [n.string - 1, n.isDead ? 'x' : n.fret]).sort(),
    })),
  )
}

function expected(score) {
  return score.measures.map((m) =>
    (m.beats.length ? m.beats : [beat([], 1)]).map((b) => ({
      duration: b.duration,
      dots: b.dots,
      tuplet: b.tuplet,
      rest: b.rest,
      notes: b.notes.map((n) => [n.string, n.dead ? 'x' : n.fret]).sort(),
    })),
  )
}

describe('alphaTab round trip', () => {
  it('exports .gp bytes that read back with the same beats and frets', () => {
    const settings = new alphaTab.Settings()
    const importer = new alphaTab.importer.AlphaTexImporter()
    importer.initFromString(scoreToTex(SCORE), settings)
    const imported = importer.readScore()
    expect(summary(imported)).toEqual(expected(SCORE))

    const bytes = new alphaTab.exporter.Gp7Exporter().export(imported, settings)
    expect(bytes).toBeInstanceOf(Uint8Array)
    expect(bytes.length).toBeGreaterThan(1000)
    expect(String.fromCharCode(bytes[0], bytes[1])).toBe('PK') // a zip, like Guitar Pro's .gp

    const back = alphaTab.importer.ScoreLoader.loadScoreFromBytes(bytes, settings)
    expect(summary(back)).toEqual(expected(SCORE))
    expect(back.title).toBe('KiLLKiSS 测试')
    expect(back.tempo).toBe(200)
    expect(back.tracks[0].staves[0].stringTuning.tunings).toEqual([64, 59, 55, 50, 45, 40, 33])
  })
})
