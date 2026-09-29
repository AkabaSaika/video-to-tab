// Verovio (LGPL, WebAssembly) renders MusicXML to SVG. It is ~7 MB, so it is imported only
// when the piano page first renders a system; the guitar pages never load it.
let toolkit = null
let queue = Promise.resolve()

function load() {
  toolkit ??= (async () => {
    const [{ default: createVerovioModule }, { VerovioToolkit }] = await Promise.all([
      import('verovio/wasm'),
      import('verovio/esm'),
    ])
    return new VerovioToolkit(await createVerovioModule())
  })()
  return toolkit
}

// One system as one line of SVG, as wide as the notation needs (scale it with CSS).
// Calls are serialized: the toolkit holds one document at a time.
export function renderSystem(musicxml, { scale = 40 } = {}) {
  const run = queue.then(async () => {
    const tk = await load()
    tk.setOptions({
      breaks: 'none',
      scale,
      adjustPageHeight: true,
      adjustPageWidth: true,
      header: 'none',
      footer: 'none',
      pageMarginTop: 20,
      pageMarginBottom: 20,
      pageMarginLeft: 20,
      pageMarginRight: 20,
    })
    if (!tk.loadData(musicxml)) throw new Error('识别结果无法显示（MusicXML 无效）')
    return fitWidth(tk.renderToSVG(1))
  })
  queue = run.catch(() => {})
  return run
}

// Verovio sizes its SVG in pixels; a viewBox lets it scale to the width of its box instead.
export function fitWidth(svg) {
  return svg.replace(
    /^<svg width="([\d.]+)px" height="([\d.]+)px"/,
    (_, w, h) => `<svg viewBox="0 0 ${w} ${h}" width="100%" preserveAspectRatio="xMinYMin meet"`,
  )
}
