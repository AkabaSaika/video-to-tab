import { describe, expect, it } from 'vitest'
import { clampRoi, displayToVideo, normalizeRect, videoToDisplay } from './roi.js'

describe('roi helpers', () => {
  it('normalizes a rectangle dragged in any direction', () => {
    expect(normalizeRect(50, 40, 10, 20)).toEqual({ x: 10, y: 20, w: 40, h: 20 })
  })

  it('round-trips between display and video coordinates', () => {
    const roi = { x: 100, y: 800, w: 1700, h: 260 }
    const scale = 1920 / 960
    expect(videoToDisplay(roi, scale)).toEqual({ x: 50, y: 400, w: 850, h: 130 })
    expect(displayToVideo(videoToDisplay(roi, scale), scale)).toEqual(roi)
  })

  it('clamps to the frame', () => {
    expect(clampRoi({ x: -5, y: 1000, w: 3000, h: 200 }, 1920, 1080)).toEqual({
      x: 0,
      y: 1000,
      w: 1920,
      h: 80,
    })
  })
})
