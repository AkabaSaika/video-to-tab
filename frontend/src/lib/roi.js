// Convert between on-screen (display) pixels and video pixels for the region editor.

export function normalizeRect(x0, y0, x1, y1) {
  return { x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) }
}

export function displayToVideo(rect, scale) {
  return {
    x: Math.round(rect.x * scale),
    y: Math.round(rect.y * scale),
    w: Math.round(rect.w * scale),
    h: Math.round(rect.h * scale),
  }
}

export function videoToDisplay(roi, scale) {
  return { x: roi.x / scale, y: roi.y / scale, w: roi.w / scale, h: roi.h / scale }
}

export function clampRoi(roi, width, height) {
  const x = Math.min(Math.max(0, roi.x), width - 1)
  const y = Math.min(Math.max(0, roi.y), height - 1)
  return {
    x,
    y,
    w: Math.max(1, Math.min(roi.w, width - x)),
    h: Math.max(1, Math.min(roi.h, height - y)),
  }
}
