// Hash routes: the guitar pages use '#job=<id>' (as before), the piano page '#/piano?job=<id>'.
export function parseHash(hash) {
  const piano = /^#\/piano(?:\?job=([\w-]*))?$/.exec(hash)
  if (piano) return { page: 'piano', job: piano[1] || null }
  const guitar = /^#job=([\w-]+)$/.exec(hash)
  return { page: 'guitar', job: guitar ? guitar[1] : null }
}

export const pianoHash = (id) => (id ? `#/piano?job=${id}` : '#/piano')
export const guitarHash = (id) => (id ? `#job=${id}` : '')

export function replaceHash(hash) {
  if (location.hash !== hash) history.replaceState(null, '', `${location.pathname}${location.search}${hash}`)
}
