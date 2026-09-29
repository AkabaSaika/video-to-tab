// Debounced autosave with at most one save in flight. An edit made while a save is running
// is saved right after it, so the newest value always lands last; a failed save is retried
// on a timer instead of waiting for the next edit.

export function createAutosaver({ save, onState, delay = 1000, retryDelay = 5000 }) {
  let latest
  let dirty = false
  let inflight = null
  let timer = null
  let state = 'saved' // saved | pending | saving | unsaved

  function setState(s) {
    state = s
    onState(s)
  }

  function schedule(ms) {
    clearTimeout(timer)
    timer = setTimeout(run, ms)
  }

  async function run() {
    clearTimeout(timer)
    timer = null
    if (inflight) return inflight // it saves again when done if still dirty
    if (!dirty) return
    const value = latest
    dirty = false
    setState('saving')
    inflight = (async () => {
      try {
        await save(value)
        inflight = null
        if (dirty) return run()
        setState('saved')
      } catch {
        inflight = null
        dirty = true
        setState('unsaved')
        schedule(retryDelay)
      }
    })()
    return inflight
  }

  return {
    change(value) {
      latest = value
      dirty = true
      if (state !== 'saving') setState('pending')
      if (!inflight) schedule(delay)
    },
    flush: () => run(),
    isClean: () => state === 'saved' && !dirty && !inflight,
  }
}
