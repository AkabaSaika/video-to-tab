// A Song (backend app/omr/model.py): { title, tempo, tracks: [Score] }, one Score per
// tab staff. score.json saved before multi-track support holds a single Score.

export function trackName(index, count) {
  return count === 1 ? 'Guitar' : `Guitar ${index + 1}`
}

export function toSong(data) {
  if (Array.isArray(data?.tracks)) return data
  const { title = '', tempo = null, ...score } = data ?? {}
  return { title, tempo, tracks: [{ ...score, name: score.name || trackName(0, 1) }] }
}

// A new song with track t replaced; the other tracks are shared.
export function setTrack(song, t, track) {
  return { ...song, tracks: song.tracks.map((old, i) => (i === t ? track : old)) }
}
