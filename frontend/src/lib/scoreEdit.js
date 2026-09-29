// Pure edits of the Score JSON: every function returns a new score and leaves its input alone.
import { DURATIONS } from './alphatex.js'

export const LOW_CONFIDENCE = 0.7
export const MAX_FRET = 30
const TUPLET_RATIO = { 3: [3, 2], 5: [5, 4], 6: [6, 4], 7: [7, 4], 9: [9, 8] }

function mapAt(list, index, fn) {
  return list.map((item, i) => (i === index ? fn(item) : item))
}

function updateMeasure(score, m, fn) {
  return { ...score, measures: mapAt(score.measures, m, fn) }
}

function updateBeat(score, m, b, fn) {
  return updateMeasure(score, m, (measure) => ({ ...measure, beats: mapAt(measure.beats, b, fn) }))
}

function restBeat(duration, x) {
  return { duration, dots: 0, tuplet: null, rest: true, notes: [], x, confidence: 1 }
}

// value: null (no note on this string), 'x' (dead note) or a fret number 0..MAX_FRET
export function setFret(score, m, b, string, value) {
  let note = null
  if (value === 'x') note = { string, fret: 0, confidence: 1, dead: true }
  else if (value !== null) {
    if (!Number.isInteger(value) || value < 0 || value > MAX_FRET) {
      throw new RangeError(`品格应为 0–${MAX_FRET} 的整数`)
    }
    note = { string, fret: value, confidence: 1, dead: false }
  }
  return updateBeat(score, m, b, (beat) => {
    const notes = beat.notes.filter((n) => n.string !== string)
    if (note) notes.push(note)
    notes.sort((p, q) => p.string - q.string)
    return { ...beat, notes, rest: notes.length === 0 }
  })
}

export function setDuration(score, m, b, duration) {
  if (!DURATIONS.includes(duration)) throw new RangeError(`不支持的时值：${duration}`)
  return updateBeat(score, m, b, (beat) => ({ ...beat, duration }))
}

export function toggleDot(score, m, b) {
  return updateBeat(score, m, b, (beat) => ({ ...beat, dots: beat.dots ? 0 : 1 }))
}

export function toggleTriplet(score, m, b) {
  return updateBeat(score, m, b, (beat) => ({ ...beat, tuplet: beat.tuplet ? null : 3 }))
}

// A rest loses its notes; turning a rest off leaves an empty beat to type frets into.
export function toggleRest(score, m, b) {
  return updateBeat(score, m, b, (beat) =>
    beat.rest ? { ...beat, rest: false } : { ...beat, rest: true, notes: [] },
  )
}

// where: 'before' | 'after'; the new beat is a rest with the neighbour's duration
export function insertBeat(score, m, b, where) {
  return updateMeasure(score, m, (measure) => {
    const ref = measure.beats[b]
    const beats = measure.beats.slice()
    beats.splice(where === 'before' ? b : b + 1, 0, restBeat(ref?.duration ?? 4, ref?.x ?? 0))
    return { ...measure, beats }
  })
}

// Deleting a measure's only beat leaves a whole-measure rest.
export function deleteBeat(score, m, b) {
  return updateMeasure(score, m, (measure) => {
    const beats = measure.beats.filter((_, i) => i !== b)
    const x = Math.round((measure.x0 + measure.x1) / 2)
    return { ...measure, beats: beats.length ? beats : [restBeat(1, x)] }
  })
}

// Marks the beat and its notes as checked. A measure whose beats now add up exactly is
// also marked checked (its low confidence means "durations did not add up").
export function confirmBeat(score, m, b) {
  const next = updateBeat(score, m, b, (beat) => ({
    ...beat,
    confidence: 1,
    notes: beat.notes.map((n) => ({ ...n, confidence: 1 })),
  }))
  const measure = next.measures[m]
  const { used, capacity } = measureFill(measure)
  if (fracCompare(used, capacity) !== 0 || measure.confidence >= 1) return next
  return updateMeasure(next, m, (mm) => ({ ...mm, confidence: 1 }))
}

// ---------------------------------------------------------------- fractions

function gcd(a, b) {
  return b ? gcd(b, a % b) : Math.abs(a)
}

function frac(n, d) {
  const g = gcd(n, d) || 1
  return { n: n / g, d: d / g }
}

export function fracCompare(a, b) {
  return Math.sign(a.n * b.d - b.n * a.d)
}

export function beatLength(beat) {
  let n = 2 ** (beat.dots + 1) - 1 // 1 + 1/2 + ... as a fraction over 2^dots
  let d = beat.duration * 2 ** beat.dots
  if (beat.tuplet) {
    const [count, time] = TUPLET_RATIO[beat.tuplet] ?? [beat.tuplet, beat.tuplet]
    n *= time
    d *= count
  }
  return frac(n, d)
}

// Length of the measure's beats vs. its time signature, both in whole notes.
export function measureFill(measure) {
  let used = { n: 0, d: 1 }
  for (const beat of measure.beats) {
    const len = beatLength(beat)
    used = frac(used.n * len.d + len.n * used.d, used.d * len.d)
  }
  const [num, den] = measure.time ?? [4, 4]
  return { used, capacity: frac(num, den) }
}

// ---------------------------------------------------------------- review

export function needsReview(measure, beat) {
  return (
    beat.confidence < LOW_CONFIDENCE ||
    beat.notes.some((n) => n.confidence < LOW_CONFIDENCE) ||
    measure.confidence < 1
  )
}

// The next flagged beat after `from` ({m, b} or null = before the start), wrapping around.
export function nextToReview(score, from) {
  const flagged = []
  score.measures.forEach((measure, m) =>
    measure.beats.forEach((beat, b) => {
      if (needsReview(measure, beat)) flagged.push({ m, b })
    }),
  )
  if (!from) return flagged[0] ?? null
  const after = flagged.find((p) => p.m > from.m || (p.m === from.m && p.b > from.b))
  return after ?? flagged[0] ?? null
}
