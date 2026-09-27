async function request(method, url, body) {
  const init = { method }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  const res = await fetch(url, init)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `请求失败 (${res.status})`)
  return data
}

export const api = {
  createFromFile(file) {
    const form = new FormData()
    form.append('file', file)
    return request('POST', '/api/jobs', form)
  },
  createFromUrl(url) {
    const form = new FormData()
    form.append('url', url)
    return request('POST', '/api/jobs', form)
  },
  getJob: (id) => request('GET', `/api/jobs/${id}`),
  setRegion: (id, region) => request('PUT', `/api/jobs/${id}/region`, region),
  exportPages: (id, order, fmt) => request('POST', `/api/jobs/${id}/export`, { order, fmt }),
  fileUrl: (id, name) => `/api/jobs/${id}/files/${name}`,
  frameUrl: (id, t) => `/api/jobs/${id}/frame?t=${t}`,
}
