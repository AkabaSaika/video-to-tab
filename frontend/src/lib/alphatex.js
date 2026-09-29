// Score JSON (see backend app/omr/model.py) -> alphaTex text for alphaTab.
import { defaultTuning, midiToName } from './tuning.js'

export const DURATIONS = [1, 2, 4, 8, 16, 32]

function quote(text) {
  return `"${String(text).replace(/[\r\n]+/g, ' ').replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`
}

// alphaTex numbers strings from the highest (1); the Score from the lowest (0).
export function texString(strings, string) {
  return strings - string
}

export function scoreTuning(score) {
  const t = score.tuning || []
  return t.length === score.strings ? t : defaultTuning(score.strings)
}

function beatTex(score, beat) {
  if (!DURATIONS.includes(beat.duration)) throw new Error(`不支持的时值：${beat.duration}`)
  let body
  if (beat.rest || !beat.notes.length) body = 'r'
  else {
    const notes = beat.notes.map((n) => {
      if (!(n.string >= 0 && n.string < score.strings)) throw new Error(`弦号超出范围：${n.string}`)
      return `${n.dead ? 'x' : n.fret}.${texString(score.strings, n.string)}`
    })
    body = notes.length === 1 ? notes[0] : `(${notes.join(' ')})`
  }
  const effects = []
  if (beat.dots) effects.push('d'.repeat(beat.dots))
  if (beat.tuplet) effects.push(`tu ${beat.tuplet}`)
  return `${body}.${beat.duration}${effects.length ? `{${effects.join(' ')}}` : ''}`
}

export function scoreToTex(score) {
  const tuning = scoreTuning(score).slice().reverse().map(midiToName).join(' ')
  const bars = score.measures.map((m) =>
    m.beats.length ? m.beats.map((b) => beatTex(score, b)).join(' ') : 'r.1',
  )
  return [
    `\\title ${quote(score.title || '')}`,
    `\\tempo ${score.tempo || 120}`,
    '.',
    '\\track "Guitar"',
    '\\staff {tabs}',
    `\\tuning (${tuning})`,
    '\\ts 4 4',
    bars.join(' |\n'),
  ].join('\n')
}
