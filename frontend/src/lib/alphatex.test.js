import { describe, expect, it } from 'vitest'
import { scoreToTex, songToTex, texString } from './alphatex.js'

const note = (string, fret, extra = {}) => ({ string, fret, confidence: 1, dead: false, ...extra })
const beat = (notes, extra = {}) => ({
  duration: 4,
  dots: 0,
  tuplet: null,
  rest: notes.length === 0,
  notes,
  x: 0,
  confidence: 1,
  ...extra,
})
const measure = (beats) => ({ number: 1, time: [4, 4], beats, line: 0, x0: 0, x1: 100, confidence: 1 })
const score7 = (measures, extra = {}) => ({
  strings: 7,
  tuning: [33, 40, 45, 50, 55, 59, 64],
  tempo: null,
  title: '',
  measures,
  ...extra,
})
const body = (tex) => tex.split('\\ts 4 4\n')[1]

describe('scoreToTex', () => {
  it('numbers strings from the highest (1) where the Score counts from the lowest (0)', () => {
    expect(texString(7, 0)).toBe(7)
    expect(texString(7, 6)).toBe(1)
    expect(texString(6, 0)).toBe(6)
    expect(body(scoreToTex(score7([measure([beat([note(0, 3)])])])))).toBe('3.7.4')
  })

  it('writes the header: title, tempo, tab staff, tuning from the highest string', () => {
    const tex = scoreToTex(score7([measure([beat([note(6, 0)])])], { title: 'Ave "M"', tempo: 200 }))
    const lines = tex.split('\n')
    expect(lines.slice(0, 7)).toEqual([
      '\\title "Ave \\"M\\""',
      '\\tempo 200',
      '.',
      '\\track "Guitar"',
      '\\staff {tabs}',
      '\\tuning (E4 B3 G3 D3 A2 E2 A1)',
      '\\ts 4 4',
    ])
  })

  it('defaults the tempo to 120 and a missing tuning to standard', () => {
    const tex = scoreToTex({ strings: 6, tuning: [], tempo: null, measures: [measure([])] })
    expect(tex).toContain('\\tempo 120')
    expect(tex).toContain('\\tuning (E4 B3 G3 D3 A2 E2)')
    expect(tex).toContain('\\title ""')
  })

  it('writes chords, dead notes, rests, dots, triplets and empty measures', () => {
    const tex = scoreToTex(
      score7([
        measure([
          beat([note(0, 7), note(1, 7)], { duration: 8 }),
          beat([note(0, 0, { dead: true })], { duration: 8 }),
          beat([], { duration: 4 }),
          beat([note(0, 5)], { duration: 8, dots: 1 }),
          beat([note(2, 12)], { duration: 8, tuplet: 3 }),
          beat([note(2, 12), note(3, 0, { dead: true })], { duration: 16, dots: 1, tuplet: 3 }),
        ]),
        measure([]),
        measure([beat([note(0, 1)], { rest: true, duration: 1 })]),
      ]),
    )
    expect(body(tex)).toBe(
      '(7.7 7.6).8 x.7.8 r.4 5.7.8{d} 12.5.8{tu 3} (12.5 x.4).16{d tu 3} |\nr.1 |\nr.1',
    )
  })

  it('refuses data alphaTab would misread', () => {
    expect(() => scoreToTex(score7([measure([beat([note(7, 1)])])]))).toThrow('弦号')
    expect(() => scoreToTex(score7([measure([beat([note(0, 1)], { duration: 3 })])]))).toThrow('时值')
  })
})

describe('songToTex', () => {
  const song = (tracks, extra = {}) => ({ title: 'S', tempo: 180, tracks, ...extra })

  it('writes one \\track per song track with its own name, tuning and bars', () => {
    const gt1 = { ...score7([measure([beat([note(0, 3)])])]), name: 'Gt.1' }
    const gt2 = {
      strings: 6,
      tuning: [38, 45, 50, 55, 59, 64],
      name: 'Gt.2',
      measures: [measure([beat([note(5, 0)])])],
    }
    const tex = songToTex(song([gt1, gt2]))
    expect(tex.split('\n').slice(0, 3)).toEqual(['\\title "S"', '\\tempo 180', '.'])
    const parts = tex.split('\\track ').slice(1)
    expect(parts).toHaveLength(2)
    expect(parts[0]).toBe(
      '"Gt.1"\n\\staff {tabs}\n\\tuning (E4 B3 G3 D3 A2 E2 A1)\n\\ts 4 4\n3.7.4\n',
    )
    expect(parts[1]).toBe('"Gt.2"\n\\staff {tabs}\n\\tuning (E4 B3 G3 D3 A2 D2)\n\\ts 4 4\n0.1.4')
  })

  it('names unnamed tracks and pads a shorter track with rest bars', () => {
    const a = score7([measure([beat([note(0, 3)])]), measure([])])
    const b = score7([measure([beat([note(0, 5)])])])
    const tex = songToTex(song([a, b]))
    expect(tex).toContain('\\track "Guitar 1"')
    expect(tex).toContain('\\track "Guitar 2"')
    expect(tex.endsWith('5.7.4 |\nr.1')).toBe(true)
  })

  it('writes tied notes with the note effect {t}, never on a dead note', () => {
    const tex = songToTex(
      song([
        score7([
          measure([
            beat([note(2, 14)], { duration: 2 }),
            beat([note(2, 14, { tied: true })], { duration: 8 }),
            beat([note(0, 5), note(1, 7, { tied: true })], { duration: 8 }),
            beat([note(0, 0, { dead: true, tied: true })], { duration: 4 }),
          ]),
        ]),
      ]),
    )
    expect(tex.split('\\ts 4 4\n')[1]).toBe('14.5.2 14.5{t}.8 (5.7 7.6{t}).8 x.7.4')
  })

  it('scoreToTex still takes a single Score', () => {
    expect(scoreToTex(score7([measure([beat([note(0, 3)])])]))).toContain('\\track "Guitar"')
  })
})
