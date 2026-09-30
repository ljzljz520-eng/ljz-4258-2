const BASE = ''

async function req(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options
  })
  const text = await res.text()
  const body = text ? JSON.parse(text) : null
  if (!res.ok) {
    const detail = body?.detail
    const msg = typeof detail === 'string'
      ? detail
      : (detail?.errors || detail?.map?.(e => e.msg || JSON.stringify(e)) || body)
    throw new Error(Array.isArray(msg) ? msg.join('; ') : JSON.stringify(msg))
  }
  return body
}

export const api = {
  health: () => req('/api/health'),
  topologies: () => req('/api/topologies'),
  batches: () => req('/api/batches'),
  batch: (id) => req(`/api/batches/${id}`),
  windows: (bid) => req(`/api/batches/${bid}/windows`),
  createWindow: (bid, body) =>
    req(`/api/batches/${bid}/windows`, { method: 'POST', body: JSON.stringify(body) }),
  preview: (wid) => req(`/api/windows/${wid}/preview`, { method: 'POST' }),
  enqueue: (wid) => req(`/api/windows/${wid}/jobs`, { method: 'POST' }),
  jobs: (wid) => req(`/api/windows/${wid}/jobs`),
  result: (wid) => req(`/api/windows/${wid}/result`),
  signoffs: (wid) => req(`/api/windows/${wid}/signoffs`),
  signoff: (rid, body) =>
    req(`/api/results/${rid}/signoff`, { method: 'POST', body: JSON.stringify(body) }),
  samples: (params = {}) => {
    const q = new URLSearchParams(params).toString()
    return req(`/api/samples${q ? `?${q}` : ''}`)
  },
  ranges: (streamId) =>
    req(`/api/ranges${streamId ? `?stream_id=${streamId}` : ''}`),
  inventories: (bid) => req(`/api/batches/${bid}/inventories`)
}
