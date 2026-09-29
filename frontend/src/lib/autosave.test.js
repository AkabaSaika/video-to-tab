import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createAutosaver } from './autosave.js'

function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => ((resolve = res), (reject = rej)))
  return { promise, resolve, reject }
}

describe('createAutosaver', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('saves the latest value once edits go quiet', async () => {
    const save = vi.fn().mockResolvedValue()
    const states = []
    const saver = createAutosaver({ save, onState: (s) => states.push(s), delay: 1000 })
    saver.change('a')
    saver.change('b')
    expect(saver.isClean()).toBe(false)
    await vi.advanceTimersByTimeAsync(1000)
    expect(save).toHaveBeenCalledTimes(1)
    expect(save).toHaveBeenCalledWith('b')
    expect(states.at(-1)).toBe('saved')
    expect(saver.isClean()).toBe(true)
  })

  it('never runs two saves at once and saves again when edited during a save', async () => {
    const first = deferred()
    const save = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue()
    const saver = createAutosaver({ save, onState: () => {}, delay: 1000 })
    saver.change('a')
    await vi.advanceTimersByTimeAsync(1000) // save('a') in flight
    saver.change('b')
    await vi.advanceTimersByTimeAsync(1000) // quiet again, but 'a' is still in flight
    expect(save).toHaveBeenCalledTimes(1)
    first.resolve()
    await vi.advanceTimersByTimeAsync(0)
    expect(save).toHaveBeenCalledTimes(2)
    expect(save).toHaveBeenLastCalledWith('b') // the newest value is written last
    expect(saver.isClean()).toBe(true)
  })

  it('retries a failed save on its own, without another edit', async () => {
    const save = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue()
    const states = []
    const saver = createAutosaver({ save, onState: (s) => states.push(s), delay: 1000, retryDelay: 5000 })
    saver.change('a')
    await vi.advanceTimersByTimeAsync(1000)
    expect(states.at(-1)).toBe('unsaved')
    expect(saver.isClean()).toBe(false)
    await vi.advanceTimersByTimeAsync(5000)
    expect(save).toHaveBeenCalledTimes(2)
    expect(save).toHaveBeenLastCalledWith('a')
    expect(states.at(-1)).toBe('saved')
  })

  it('flush saves pending changes immediately', async () => {
    const save = vi.fn().mockResolvedValue()
    const saver = createAutosaver({ save, onState: () => {}, delay: 1000 })
    saver.change('a')
    await saver.flush()
    expect(save).toHaveBeenCalledWith('a')
    expect(saver.isClean()).toBe(true)
    await vi.advanceTimersByTimeAsync(5000)
    expect(save).toHaveBeenCalledTimes(1) // nothing left over
  })
})
