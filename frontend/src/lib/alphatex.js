// Song / Score JSON (see backend app/omr/model.py) -> alphaTex text for alphaTab.
import { toSong, trackName } from './song.js'
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

const SLIDE_OUT = { shift: 'ss', legato: 'sl', out_down: 'sod', out_up: 'sou' }
const SLIDE_IN = { below: 'sib', above: 'sia' }
const HARMONIC = { artificial: 'ah', pinch: 'ph', tap: 'th', semi: 'sh', feedback: 'fh' }

// Note effects of a note's playing techniques (see Note in backend app/omr/model.py).
// Bends are stored in semitones; alphaTex bend values are quarter tones.
export function techniqueEffects(n) {
  const out = []
  const quarters = Math.round((n.bend || 0) * 2)
  if (quarters > 0) {
    out.push(n.bend_release ? `be (bendRelease 0 0 30 ${quarters} 60 0)` : `b (0 ${quarters})`)
  }
  if (n.harmonic === 'natural') out.push('nh')
  else if (HARMONIC[n.harmonic]) out.push(`${HARMONIC[n.harmonic]} ${n.harmonic_fret ?? 12}`)
  if (n.vibrato) out.push('v')
  if (SLIDE_IN[n.slide_in]) out.push(SLIDE_IN[n.slide_in])
  if (SLIDE_OUT[n.slide]) out.push(SLIDE_OUT[n.slide])
  if (n.hopo) out.push('h')
  if (n.palm_mute) out.push('pm')
  if (n.staccato) out.push('st')
  return out
}

function beatTex(score, beat) {
  if (!DURATIONS.includes(beat.duration)) throw new Error(`不支持的时值：${beat.duration}`)
  let body
  if (beat.rest || !beat.notes.length) body = 'r'
  else {
    const notes = beat.notes.map((n) => {
      if (!(n.string >= 0 && n.string < score.strings)) throw new Error(`弦号超出范围：${n.string}`)
      // t: tied to the previous note on this string (alphaTab's isTieDestination)
      const effects = [...(n.tied && !n.dead ? ['t'] : []), ...techniqueEffects(n)]
      const fx = effects.length ? `{${effects.join(' ')}}` : ''
      return `${n.dead ? 'x' : n.fret}.${texString(score.strings, n.string)}${fx}`
    })
    body = notes.length === 1 ? notes[0] : `(${notes.join(' ')})`
  }
  const effects = []
  if (beat.dots) effects.push('d'.repeat(beat.dots))
  if (beat.tuplet) effects.push(`tu ${beat.tuplet}`)
  return `${body}.${beat.duration}${effects.length ? `{${effects.join(' ')}}` : ''}`
}

function trackTex(track, index, count, bars) {
  const tuning = scoreTuning(track).slice().reverse().map(midiToName).join(' ')
  const body = []
  for (let i = 0; i < bars; i++) {
    const m = track.measures[i]
    body.push(m?.beats.length ? m.beats.map((b) => beatTex(track, b)).join(' ') : 'r.1')
  }
  return [
    `\\track ${quote(track.name || trackName(index, count))}`,
    '\\staff {tabs}',
    `\\tuning (${tuning})`,
    '\\ts 4 4',
    body.join(' |\n'),
  ].join('\n')
}

// Every track of the song; a shorter track is padded with rest bars so all tracks
// have the same bars (alphaTab lays bars of all tracks out together).
export function songToTex(data) {
  const song = toSong(data)
  const bars = Math.max(0, ...song.tracks.map((t) => t.measures.length))
  return [
    `\\title ${quote(song.title || '')}`,
    `\\tempo ${song.tempo || 120}`,
    '.',
    ...song.tracks.map((t, i) => trackTex(t, i, song.tracks.length, bars)),
  ].join('\n')
}

// A single Score (one track).
export function scoreToTex(score) {
  return songToTex(score)
}
