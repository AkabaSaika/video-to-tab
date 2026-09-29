// Which page image a measure was recognized from. Measure.line indexes job.score_files
// (the files recorded at recognition; older jobs only have score_order page ids).
// kind: 'page' (with file) | 'absent' (padding: not in the video) | 'missing'
export function measureSource(job, measure) {
  if (measure.line < 0) return { kind: 'absent' }
  if (job.score_files?.length) {
    const file = job.score_files[measure.line]
    return file ? { kind: 'page', file } : { kind: 'missing' }
  }
  const id = job.score_order?.[measure.line]
  const page = job.pages.find((p) => p.id === id)
  return page ? { kind: 'page', file: page.file } : { kind: 'missing' }
}
