// Round trip in Node: Score -> alphaTex -> alphaTab -> Gp7Exporter bytes -> ScoreLoader.
import * as alphaTab from '@coderline/alphatab'
import { describe, expect, it } from 'vitest'
import { scoreToTex, songToTex } from './alphatex.js'

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

// Two tracks with ties (a held note, a tied chord), different string counts and tunings.
const SONG = {
  title: 'Ties',
  tempo: 180,
  tracks: [
    {
      name: 'Gt.1',
      strings: 6,
      tuning: [40, 45, 50, 55, 59, 64],
      measures: [
        measure([
          beat([note(3, 14)], 2),
          beat([{ ...note(3, 14), tied: true }], 8),
          beat([note(3, 12)], 4),
          beat([note(3, 14)], 8),
        ]),
        measure([beat([{ ...note(3, 14), tied: true }], 8), beat([note(2, 12)], 8), beat([], 4), beat([], 2)]),
      ],
    },
    {
      name: 'Gt.2',
      strings: 7,
      tuning: [33, 40, 45, 50, 55, 59, 64],
      measures: [
        measure([
          beat([], 8),
          beat([note(0, 1), note(1, 3), note(2, 3)], 8),
          beat([], 8),
          beat([note(0, 1), note(1, 3), note(2, 3)], 8),
          beat([0, 1, 2].map((s) => ({ ...note(s, [1, 3, 3][s]), tied: true })), 8),
          beat([note(0, 1), note(1, 3), note(2, 3)], 8),
          beat([note(0, 1), note(1, 3), note(2, 3)], 4),
        ]),
        measure([]),
      ],
    },
  ],
}

function songSummary(score) {
  return score.tracks.map((t) => ({
    name: t.name,
    tuning: t.staves[0].stringTuning.tunings,
    bars: t.staves[0].bars.map((bar) =>
      bar.voices[0].beats.map((b) => ({
        duration: b.duration,
        rest: b.isRest,
        notes: b.notes.map((n) => [n.string - 1, n.fret, n.isTieDestination]).sort(),
      })),
    ),
  }))
}

function songExpected(song) {
  return song.tracks.map((t) => ({
    name: t.name,
    tuning: t.tuning.slice().reverse(),
    bars: t.measures.map((m) =>
      (m.beats.length ? m.beats : [beat([], 1)]).map((b) => ({
        duration: b.duration,
        rest: b.rest,
        notes: b.notes.map((n) => [n.string, n.fret, !!n.tied]).sort(),
      })),
    ),
  }))
}

describe('alphaTab round trip of a song', () => {
  it('exports every track, with ties, to one .gp file', () => {
    const settings = new alphaTab.Settings()
    const importer = new alphaTab.importer.AlphaTexImporter()
    importer.initFromString(songToTex(SONG), settings)
    const imported = importer.readScore()
    expect(songSummary(imported)).toEqual(songExpected(SONG))

    const bytes = new alphaTab.exporter.Gp7Exporter().export(imported, settings)
    const back = alphaTab.importer.ScoreLoader.loadScoreFromBytes(bytes, settings)
    expect(songSummary(back)).toEqual(songExpected(SONG))
    expect(back.title).toBe('Ties')
    expect(back.tempo).toBe(180)
  })
})

// Every technique, alone and combined, on a 6-string track.
const TECH = [
  { bend: 1 },
  { bend: 2 },
  { bend: 3, bend_release: true },
  { slide: 'shift' },
  { slide: 'legato' },
  { slide: 'out_down' },
  { slide: 'out_up' },
  { slide_in: 'below' },
  { slide_in: 'above', slide: 'out_down' },
  { hopo: true },
  { harmonic: 'natural', harmonic_fret: 7 }, // natural: at the note's own fret (5 + 10 % 4)
  { harmonic: 'artificial', harmonic_fret: 5 },
  { harmonic: 'pinch', harmonic_fret: 12 },
  { harmonic: 'tap', harmonic_fret: 12 },
  { harmonic: 'semi', harmonic_fret: 5 },
  { harmonic: 'feedback', harmonic_fret: 7 },
  { vibrato: true },
  { palm_mute: true },
  { staccato: true },
  { palm_mute: true, staccato: true, vibrato: true },
]

const HARMONIC_TYPES = ['', 'natural', 'artificial', 'pinch', 'tap', 'semi', 'feedback']
const SLIDE_OUT = ['', 'shift', 'legato', 'out_up', 'out_down']
const SLIDE_IN = ['', 'below', 'above']

// alphaTab note -> the technique fields of the Score JSON (only the ones set)
function techOf(n) {
  const t = {}
  if (n.hasBend) {
    const values = n.bendPoints.map((p) => p.value)
    const peak = Math.max(...values)
    t.bend = peak / 2
    if (values[values.length - 1] < peak) t.bend_release = true
  }
  if (SLIDE_OUT[n.slideOutType]) t.slide = SLIDE_OUT[n.slideOutType]
  if (SLIDE_IN[n.slideInType]) t.slide_in = SLIDE_IN[n.slideInType]
  if (n.isHammerPullOrigin) t.hopo = true
  if (HARMONIC_TYPES[n.harmonicType]) {
    t.harmonic = HARMONIC_TYPES[n.harmonicType]
    t.harmonic_fret = n.harmonicValue
  }
  if (n.vibrato) t.vibrato = true
  if (n.isPalmMute) t.palm_mute = true
  if (n.isStaccato) t.staccato = true
  return t
}

describe('alphaTab round trip of playing techniques', () => {
  it('exports every technique to .gp and reads it back unchanged', () => {
    const quarter = (t, i) => beat([{ ...note(2, 5 + (i % 4)), ...t }], 4)
    const song = {
      title: 'Techniques',
      tempo: 120,
      tracks: [
        {
          name: 'Gt',
          strings: 6,
          tuning: [40, 45, 50, 55, 59, 64],
          measures: [0, 4, 8, 12, 16].map((k) => measure(TECH.slice(k, k + 4).map(quarter))),
        },
      ],
    }
    const settings = new alphaTab.Settings()
    const importer = new alphaTab.importer.AlphaTexImporter()
    importer.initFromString(songToTex(song), settings)
    const bytes = new alphaTab.exporter.Gp7Exporter().export(importer.readScore(), settings)
    const back = alphaTab.importer.ScoreLoader.loadScoreFromBytes(bytes, settings)
    const got = back.tracks[0].staves[0].bars.flatMap((bar) =>
      bar.voices[0].beats.map((b) => techOf(b.notes[0])),
    )
    expect(got).toEqual(TECH)
  })
})
