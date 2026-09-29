// Tunings as MIDI numbers, lowest string first (the Score's string order: 0 = lowest).
// Text form lists note names from the highest string down, like alphaTex's \tuning.

const NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
const STEPS = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }

export const PRESETS = {
  6: [
    { name: 'E 标准', tuning: [40, 45, 50, 55, 59, 64] },
    { name: 'Drop D', tuning: [38, 45, 50, 55, 59, 64] },
    { name: '降半音', tuning: [39, 44, 49, 54, 58, 63] },
  ],
  7: [
    { name: 'B 标准', tuning: [35, 40, 45, 50, 55, 59, 64] },
    { name: 'Drop A', tuning: [33, 40, 45, 50, 55, 59, 64] },
  ],
}

export function midiToName(midi) {
  return `${NAMES[midi % 12]}${Math.floor(midi / 12) - 1}`
}

// 'E4' / 'F#2' / 'Bb1' (case-insensitive letter) -> MIDI number, or null if not a note name
export function nameToMidi(name) {
  const m = /^([A-Ga-g])(#|b)?(\d)$/.exec(String(name).trim())
  if (!m) return null
  const shift = m[2] === '#' ? 1 : m[2] === 'b' ? -1 : 0
  const midi = (Number(m[3]) + 1) * 12 + STEPS[m[1].toUpperCase()] + shift
  return midi >= 0 && midi <= 127 ? midi : null
}

// 'E4 B3 G3 D3 A2 E2' (highest string first) -> [40, 45, ...] (lowest first); throws on bad input
export function parseTuning(text, strings) {
  const parts = String(text).trim().split(/[\s,]+/).filter(Boolean)
  if (parts.length !== strings) {
    throw new Error(`需要 ${strings} 个音名（从最高音弦写到最低音弦），实际 ${parts.length} 个`)
  }
  const midi = parts.map((p) => {
    const v = nameToMidi(p)
    if (v === null) throw new Error(`无法识别的音名：${p}（例如 E4、F#2、Bb1）`)
    return v
  })
  return midi.reverse()
}

export function tuningText(tuning) {
  return tuning.slice().reverse().map(midiToName).join(' ')
}

// The first preset for this string count; other counts stack fourths (one major third)
// down from E4, which gives standard tuning for 6, 7 and 8 strings.
export function defaultTuning(strings) {
  if (PRESETS[strings]) return PRESETS[strings][0].tuning.slice()
  const gaps = [5, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5]
  const high = [64]
  for (let i = 1; i < strings; i++) high.push(high[i - 1] - gaps[i - 1])
  return high.reverse()
}
