import { describe, expect, it } from 'vitest'
import { renderSystem } from './verovio.js'

const xml = `<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
<part id="P1"><measure number="1"><attributes><divisions>1</divisions><staves>2</staves>
<key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time>
<clef number="1"><sign>G</sign><line>2</line></clef><clef number="2"><sign>F</sign><line>4</line></clef></attributes>
<note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><voice>1</voice><type>whole</type><staff>1</staff></note>
<backup><duration>4</duration></backup>
<note><pitch><step>C</step><octave>3</octave></pitch><duration>4</duration><voice>5</voice><type>whole</type><staff>2</staff></note>
</measure></part></score-partwise>`

describe('verovio', () => {
  it('loads the WebAssembly toolkit and renders a grand staff to SVG', async () => {
    const svg = await renderSystem(xml)
    expect(svg).toMatch(/^<svg viewBox="0 0 \d+ \d+" width="100%"/)
    expect(svg.match(/class="staff"/g)).toHaveLength(2)
    expect(svg.match(/class="note"/g)).toHaveLength(2)
    // calls queue up and still work after a bad document
    await expect(renderSystem('<nope/>')).rejects.toThrow()
    expect(await renderSystem(xml)).toMatch(/^<svg/)
  }, 30000)
})
