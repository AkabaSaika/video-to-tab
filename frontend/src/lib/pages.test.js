import { describe, expect, it } from 'vitest'
import { formatTime, moveItem } from './pages.js'

describe('page helpers', () => {
  it('moves an item without mutating the input', () => {
    const list = [0, 1, 2, 3]
    expect(moveItem(list, 3, 1)).toEqual([0, 3, 1, 2])
    expect(list).toEqual([0, 1, 2, 3])
  })

  it('formats seconds as m:ss.s', () => {
    expect(formatTime(65.25)).toBe('1:05.3')
    expect(formatTime(3)).toBe('0:03.0')
  })
})
