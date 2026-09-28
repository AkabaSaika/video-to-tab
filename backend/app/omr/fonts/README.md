# Training fonts

Open-licensed fonts used only to render synthetic training glyphs (`app/omr/train.py`).
Each file is a subset containing just the characters the generator draws, made with:

    uvx --from fonttools pyftsubset FONT.ttf \
        --text='0123456789()xX×<>~^vPMhpbrsHT/\*+=' \
        --no-hinting --desubroutinize --layout-features='' --output-file=FONT.ttf

Licenses: `LICENSE-OFL.txt` (Fira Sans, Inter, Lato, Noto Sans/Serif, Open Sans, Oswald,
PT Sans/Serif, Roboto, Source Sans 3, Work Sans), `LICENSE-Liberation.txt` (Liberation
Sans/Serif, Arimo, Tinos; SIL OFL 1.1), `LICENSE-DejaVu.txt` (DejaVu Sans/Serif),
`LICENSE-Ubuntu.txt` (Ubuntu).
