import { describe, expect, it } from 'vitest'
import { PRESETS, defaultTuning, midiToName, nameToMidi, parseTuning, tuningText } from './tuning.js'

describe('tuning', () => {
  it('converts names and MIDI both ways', () => {
    expect(midiToName(64)).toBe('E4')
    expect(midiToName(33)).toBe('A1')
    expect(midiToName(42)).toBe('F#2')
    expect(nameToMidi('E4')).toBe(64)
    expect(nameToMidi('e2')).toBe(40)
    expect(nameToMidi('Bb1')).toBe(34)
    expect(nameToMidi('F#2')).toBe(42)
    for (let midi = 12; midi < 120; midi++) expect(nameToMidi(midiToName(midi))).toBe(midi)
  })

  it('rejects bad note names', () => {
    for (const bad of ['', 'H2', 'E', '4', 'E#', 'Ex4', 'E10', 'E-1']) {
      expect(nameToMidi(bad)).toBeNull()
    }
  })

  it('has the presets named in the spec, lowest string first', () => {
    expect(PRESETS[6].map((p) => p.name)).toEqual(['E 标准', 'Drop D', '降半音'])
    expect(PRESETS[7].map((p) => p.name)).toEqual(['B 标准', 'Drop A'])
    expect(tuningText(PRESETS[7][1].tuning)).toBe('E4 B3 G3 D3 A2 E2 A1')
    expect(tuningText(PRESETS[6][2].tuning)).toBe('D#4 A#3 F#3 C#3 G#2 D#2')
    for (const [strings, list] of Object.entries(PRESETS)) {
      for (const p of list) expect(p.tuning).toHaveLength(Number(strings))
    }
  })

  it('parses custom tunings written from the highest string', () => {
    expect(parseTuning('E4 B3 G3 D3 A2 D2', 6)).toEqual([38, 45, 50, 55, 59, 64])
    expect(parseTuning('  e4,b3 g3  d3 a2 e2 ', 6)).toEqual([40, 45, 50, 55, 59, 64])
    expect(() => parseTuning('E4 B3 G3', 6)).toThrow('需要 6 个音名')
    expect(() => parseTuning('E4 B3 G3 D3 A2 X2', 6)).toThrow('X2')
  })

  it('falls back to standard tuning for any string count', () => {
    expect(defaultTuning(6)).toEqual([40, 45, 50, 55, 59, 64])
    expect(defaultTuning(7)).toEqual([35, 40, 45, 50, 55, 59, 64])
    expect(tuningText(defaultTuning(8))).toBe('E4 B3 G3 D3 A2 E2 B1 F#1')
    expect(defaultTuning(4)).toHaveLength(4)
  })
})
