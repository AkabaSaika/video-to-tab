"""Playing techniques: shape tests on marks measured in real Guitar Pro renderings, and
recognition on synthetic tab lines with the marks drawn in (they must never add notes)."""

import cv2
import numpy as np
import pytest

from app.omr.glyphs import MODEL_PATH, Blob
from app.omr.recognize import recognize_images
from app.omr.techniques import (
    Run,
    bend_amount,
    chevron,
    is_diagonal,
    is_palm_mute,
    is_wave,
    letter_kind,
)
from tests.test_omr_recognize import SPACING, TOP, draw_line, notes_of, only_track


def blob(rows, x=0, y=0):
    mask = np.array([[c == "#" for c in r] for r in rows])
    return Blob(x, y, mask.shape[1], mask.shape[0], mask)


def box(x, y, w, h, fill=True):
    """A blob of the given box, solid (a dot, a stroke) or an outline (a letter)."""
    m = np.ones((h, w), bool)
    if not fill and h > 2 and w > 2:
        m[1:-1, 1:-1] = False
    return Blob(x, y, w, h, m)


# ---------------------------------------------------------------- measured shapes

# tie1 (BV16g4y1T78b, s = 19.6 px): the serif "H" and "P" above hammer-ons and pull-offs
H_SERIF = [
    "#####..#####",
    ".##.....###.",
    ".##......##.",
    ".##......##.",
    ".##......##.",
    ".###....###.",
    ".##########.",
    ".##......##.",
    ".##......##.",
    ".##.....###.",
    ".##......##.",
    ".###....###.",
    ".##.......#.",
]
P_SERIF = [
    "#######..",
    ".###.###.",
    ".##...###",
    ".##....##",
    ".##....##",
    ".###..###",
    ".######..",
    ".##......",
    ".##......",
    ".##......",
    ".##......",
    ".###.....",
    ".#.#.....",
]
# gp1 (BV1yBcEeXEVn, s = 32 px): a slide out of a note ("2\\"), and the end of a tie arc
# cut at a bar line, which is also slanted but bent and flatter
SLIDE = [
    ".##....................",
    "####...................",
    "#####..................",
    ".#####.................",
    "..#####................",
    "...#####...............",
    "....#####..............",
    ".....#####.............",
    "......#####............",
    ".......#####...........",
    "........#####..........",
    "..........###..........",
    "..........#####........",
    "...........#####.......",
    "............#####......",
    ".............#####.....",
    "..............#####....",
    "...............#####...",
    "................#####..",
    ".................#####.",
    "..................#####",
    "...................###.",
    "....................#..",
]
ARC_END = [
    ".........................#",
    "........................#.",
    "......................##..",
    "....................##....",
    ".................####.....",
    "...............####.......",
    "............#####.........",
    ".........######...........",
    "......#######.............",
    "###########...............",
    "########..................",
    "######....................",
    "##........................",
]


def test_letters_by_topology():
    assert letter_kind(blob(H_SERIF)) == "H"
    assert letter_kind(blob(P_SERIF)) == "P"
    # an "M" (P.M.) has no loop but its middle reaches the top: not an H
    m = np.zeros((13, 14), bool)
    m[:, :2] = m[:, -2:] = True
    for i in range(7):
        m[i * 2 : i * 2 + 2, i] = m[i * 2 : i * 2 + 2, 13 - i] = True
    assert letter_kind(Blob(0, 0, 14, 13, m)) is None
    # a "0" has its loop in the middle and ink on both sides at the bottom
    ring = np.zeros((13, 9), bool)
    ring[[0, -1], 1:-1] = True
    ring[1:-1, [0, -1]] = True
    assert letter_kind(Blob(0, 0, 9, 13, ring)) is None


def test_slide_is_straight_and_steep_an_arc_end_is_not():
    s = 32.0
    assert is_diagonal(blob(SLIDE), s)
    assert not is_diagonal(blob(ARC_END), s)
    assert not is_diagonal(blob(["#" * 20] * 2), s)  # a bit of staff line


def test_palm_mute_text_as_guitar_pro_draws_it():
    """gp1 m30, s = 32: "P" 23x26, ".", "M" in two pieces (a stitching seam), ".", a speck."""
    s = 32.0
    run = Run(
        [
            box(267, 48, 23, 26, fill=False),
            box(289, 68, 6, 6),
            box(298, 48, 19, 26, fill=False),
            box(317, 48, 16, 26, fill=False),
            box(336, 68, 6, 6),
        ]
    )
    assert is_palm_mute(run, s)
    speck = Run([*run.blobs, box(300, 73, 2, 1)])
    assert is_palm_mute(speck, s)
    # "sl." (one dot) and "P.M" without its last dot are not palm mutes
    assert not is_palm_mute(Run(run.blobs[:-1]), s)
    assert not is_palm_mute(
        Run([box(0, 60, 12, 16, False), box(14, 50, 5, 26), box(21, 71, 4, 4)]), s
    )


def test_bend_labels():
    s = 20.0
    digit = {id_: d for id_, d in []}  # noqa: F841 - the classifier is not needed here

    def no_digit(_):
        return None

    # "full": letters on one baseline
    full = Run([box(0, 0, 6, 14), box(7, 5, 6, 9), box(14, 0, 3, 14), box(18, 0, 3, 14)])
    assert bend_amount(full, s, no_digit) == 2.0
    # "1/2": small "1" high, "/" and "2" low
    half = Run([box(0, 0, 4, 8), box(3, 0, 8, 16, fill=False), box(9, 8, 6, 8)])
    assert bend_amount(half, s, no_digit) == 1.0
    # "1 1/2": a full-size digit before the fraction
    big = box(-10, 0, 6, 16)
    assert bend_amount(Run([big, *half.blobs]), s, lambda b: 1 if b is big else None) == 3.0
    assert bend_amount(None, s, no_digit) == 2.0  # label cut off: full


def test_chevrons_and_wave():
    s = 24.0
    lt = np.zeros((12, 8), bool)
    for i in range(12):
        lt[i, int(round(abs(i - 5.5) * 7 / 5.5))] = True
    assert chevron(Blob(0, 0, 8, 12, lt), s) == "<"
    assert chevron(Blob(0, 0, 8, 12, lt[:, ::-1]), s) == ">"
    assert chevron(blob(SLIDE), s) is None
    xs = np.arange(60)
    wave = np.zeros((9, 60), bool)
    wave[(4 + 3 * np.sin(xs / 3)).round().astype(int), xs] = True
    assert is_wave(Blob(0, 0, 60, 9, wave), s)
    assert not is_wave(Blob(0, 0, 60, 2, np.ones((2, 60), bool)), s)


# ---------------------------------------------------------------- synthetic lines

BEAT_W, PAD, LEAD = 90, 30, 10


def beat_x(m, k):
    """Left of the number of beat k in measure m (as draw_line puts it)."""
    return LEAD + m * (4 * BEAT_W + PAD) + PAD + k * BEAT_W


def line_y(string, strings=6):
    return TOP + (strings - 1 - string) * SPACING


def text(img, t, x, y, scale=0.6, thick=1):
    cv2.putText(img, t, (x, y), cv2.FONT_HERSHEY_TRIPLEX, scale, (0, 0, 0), thick, cv2.LINE_AA)


def palm_mute(img, x, y, dashes_to=None):
    """ "P.M." with its dots, centered on x, baseline y; dashes and a tick to dashes_to."""
    (pw, ph), _ = cv2.getTextSize("P", cv2.FONT_HERSHEY_TRIPLEX, 0.55, 1)
    (mw, _), _ = cv2.getTextSize("M", cv2.FONT_HERSHEY_TRIPLEX, 0.55, 1)
    x0 = x - (pw + mw + 20) // 2
    cv2.putText(img, "P", (x0, y), cv2.FONT_HERSHEY_TRIPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.circle(img, (x0 + pw + 4, y - 2), 2, (0, 0, 0), -1)
    cv2.putText(
        img, "M", (x0 + pw + 10, y), cv2.FONT_HERSHEY_TRIPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA
    )
    end = x0 + pw + mw + 16
    cv2.circle(img, (end, y - 2), 2, (0, 0, 0), -1)
    if dashes_to:
        mid = y - ph // 2
        d = end + 12
        while d + 8 < dashes_to:
            cv2.line(img, (d, mid), (d + 7, mid), (0, 0, 0), 2)
            d += 16
        cv2.line(img, (dashes_to, mid - 7), (dashes_to, mid + 7), (0, 0, 0), 2)


def techniques_of(score):
    names = ("bend", "slide", "slide_in", "hopo", "harmonic", "vibrato", "palm_mute", "staccato")
    return [
        [
            {
                (n.string, n.fret): {k: getattr(n, k) for k in names if getattr(n, k)}
                for n in b.notes
            }
            for b in m.beats
        ]
        for m in score.measures
    ]


needs_model = pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
STRAIGHT = [[[(0, 3)], [(0, 3)], [(0, 3)], [(0, 3)]], [[(0, 5)], [(0, 5)], [(0, 5)], [(0, 5)]]]


@needs_model
def test_palm_mute_covers_its_dashed_extent_and_a_bare_one_its_beat():
    img = draw_line(STRAIGHT)
    palm_mute(img, beat_x(0, 0) + 6, TOP - 14, dashes_to=beat_x(0, 2) + 12)
    palm_mute(img, beat_x(1, 1) + 6, TOP - 14)
    track = only_track(recognize_images([img]))
    assert notes_of(track) == [[[(0, 3)]] * 4, [[(0, 5)]] * 4]
    pm = [[b.notes[0].palm_mute for b in m.beats] for m in track.measures]
    assert pm == [[True, True, True, False], [False, True, False, False]]


@needs_model
def test_staccato_dot_above_the_staff():
    img = draw_line(STRAIGHT)
    for m, k in ((0, 1), (1, 3)):
        cv2.circle(img, (beat_x(m, k) + 6, TOP - 12), 2, (0, 0, 0), -1)
    track = only_track(recognize_images([img]))
    assert notes_of(track) == [[[(0, 3)]] * 4, [[(0, 5)]] * 4]
    st = [[b.notes[0].staccato for b in m.beats] for m in track.measures]
    assert st == [[False, True, False, False], [False, False, False, True]]


@needs_model
def test_hammer_on_and_pull_off_letters():
    measures = [[[(4, 5)], [(4, 7)], [(4, 7)], [(4, 5)]], [[(2, 2)], [(2, 4)], [(1, 3)], [(1, 3)]]]
    img = draw_line(measures)
    text(img, "H", (beat_x(0, 0) + beat_x(0, 1)) // 2, TOP - 8, 0.5)
    text(img, "P", (beat_x(0, 2) + beat_x(0, 3)) // 2, TOP - 8, 0.5)
    y = line_y(4) - 12  # the slur of the hammer-on
    cv2.ellipse(img, ((beat_x(0, 0) + beat_x(0, 1)) // 2 + 6, y), (40, 8), 0, 180, 360, 0, 1)
    # an arc between different frets of one string, without a letter, is a hammer-on too
    cv2.ellipse(
        img, ((beat_x(1, 0) + beat_x(1, 1)) // 2 + 6, line_y(2) - 12), (34, 8), 0, 180, 360, 0, 1
    )
    track = only_track(recognize_images([img]))
    assert notes_of(track) == [
        [[n] for n in [(4, 5), (4, 7), (4, 7), (4, 5)]],
        [[n] for n in [(2, 2), (2, 4), (1, 3), (1, 3)]],
    ]
    hopo = [[b.notes[0].hopo for b in m.beats] for m in track.measures]
    assert hopo == [[True, False, True, False], [True, False, False, False]]


@needs_model
def test_slides_between_into_and_out_of_notes():
    measures = [[[(3, 5)], [(3, 3)], [(1, 7)], [(3, 9)]], [[(2, 5)], [(2, 7)], [(0, 3)], [(0, 3)]]]
    img = draw_line(measures)

    def diag(x, string, down):
        y = line_y(string)
        a, b = (y - 7, y + 7) if down else (y + 7, y - 7)
        cv2.line(img, (x, a), (x + 14, b), (0, 0, 0), 2, cv2.LINE_AA)

    y = line_y(3)  # 5 \ 3: a shift slide, a line from note to note
    cv2.line(img, (beat_x(0, 0) + 20, y - 7), (beat_x(0, 1) - 8, y + 7), (0, 0, 0), 2, cv2.LINE_AA)
    diag(beat_x(0, 3) - 22, 3, down=False)  # / 9: slide in from below
    y = line_y(2)  # 5 / 7 under "sl.": a legato slide
    cv2.line(img, (beat_x(1, 0) + 20, y + 7), (beat_x(1, 1) - 8, y - 7), (0, 0, 0), 2, cv2.LINE_AA)
    text(img, "sl", beat_x(1, 0) + 20, TOP - 10, 0.5)
    cv2.circle(img, (beat_x(1, 0) + 44, TOP - 12), 2, (0, 0, 0), -1)
    diag(beat_x(1, 3) + 24, 0, down=True)  # 3 \ : slide out downwards
    track = only_track(recognize_images([img]))
    assert notes_of(track) == [
        [[n] for n in m]
        for m in [[(3, 5), (3, 3), (1, 7), (3, 9)], [(2, 5), (2, 7), (0, 3), (0, 3)]]
    ]
    got = [[(b.notes[0].slide, b.notes[0].slide_in) for b in m.beats] for m in track.measures]
    assert got == [
        [("shift", None), (None, None), (None, None), (None, "below")],
        [("legato", None), (None, None), (None, None), ("out_down", None)],
    ]


def arrow(img, x, y, top):
    """A bend arrow from beside a number at (x, y) curving up to `top`."""
    pts = np.array([(x, y), (x + 10, y - 4), (x + 16, y - 16), (x + 18, top + 6)], np.int32)
    cv2.polylines(img, [pts], False, (0, 0, 0), 1, cv2.LINE_AA)
    head = np.array([(x + 14, top + 8), (x + 18, top), (x + 22, top + 8)], np.int32)
    cv2.fillPoly(img, [head], (0, 0, 0))


@needs_model
def test_bend_arrows_with_their_labels():
    measures = [[[(4, 7)], [(4, 7)], [(3, 9)], [(3, 9)]], STRAIGHT[1]]
    img = draw_line(measures)
    arrow(img, beat_x(0, 0) + 16, line_y(4) - 4, TOP - 30)
    text(img, "full", beat_x(0, 0) + 20, TOP - 40, 0.4)
    arrow(img, beat_x(0, 2) + 16, line_y(3) - 4, TOP - 30)
    # a stacked "1/2" a little above the arrow's tip, as in gp1
    text(img, "1", beat_x(0, 2) + 28, TOP - 49, 0.35)
    cv2.line(img, (beat_x(0, 2) + 33, TOP - 38), (beat_x(0, 2) + 42, TOP - 54), 0, 1)
    text(img, "2", beat_x(0, 2) + 38, TOP - 39, 0.35)
    track = only_track(recognize_images([img]))
    assert notes_of(track) == [[[n] for n in [(4, 7), (4, 7), (3, 9), (3, 9)]], [[(0, 5)]] * 4]
    bends = [b.notes[0].bend for b in track.measures[0].beats]
    assert bends == [2.0, None, 1.0, None]


@needs_model
def test_bracketed_numbers_are_harmonics_not_notes():
    measures = [[[(2, 12)], [(3, 7)], [(0, 3)], [(0, 3)]], STRAIGHT[1]]
    img = draw_line(measures)
    y = line_y(2)
    # natural harmonic: the fret itself in angle brackets
    cv2.polylines(
        img,
        [np.array([(beat_x(0, 0) - 3, y - 7), (beat_x(0, 0) - 10, y), (beat_x(0, 0) - 3, y + 7)])],
        False,
        0,
        1,
    )
    cv2.polylines(
        img,
        [
            np.array(
                [(beat_x(0, 0) + 30, y - 7), (beat_x(0, 0) + 37, y), (beat_x(0, 0) + 30, y + 7)]
            )
        ],
        False,
        0,
        1,
    )
    # artificial harmonic: a small "<19>" right of the 7
    x, y = beat_x(0, 1) + 18, line_y(3)
    cv2.rectangle(img, (x - 2, y - 8), (x + 40, y + 8), (255, 255, 255), -1)
    cv2.polylines(img, [np.array([(x + 6, y - 6), (x, y), (x + 6, y + 6)])], False, 0, 1)
    cv2.putText(img, "19", (x + 9, y + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, 0, 1, cv2.LINE_AA)
    cv2.polylines(img, [np.array([(x + 32, y - 6), (x + 38, y), (x + 32, y + 6)])], False, 0, 1)
    track = only_track(recognize_images([img]))
    assert notes_of(track) == [[[n] for n in [(2, 12), (3, 7), (0, 3), (0, 3)]], [[(0, 5)]] * 4]
    first, second = (track.measures[0].beats[k].notes[0] for k in (0, 1))
    assert (first.harmonic, first.harmonic_fret) == ("natural", 12.0)
    assert (second.harmonic, second.harmonic_fret) == ("artificial", 12.0)


@needs_model
def test_wavy_line_is_vibrato():
    img = draw_line(STRAIGHT)
    xs = np.arange(beat_x(1, 2), beat_x(1, 2) + 50)
    pts = np.stack([xs, TOP - 14 + 3 * np.sin((xs - xs[0]) / 3)], axis=1).astype(np.int32)
    cv2.polylines(img, [pts], False, (0, 0, 0), 2, cv2.LINE_AA)
    track = only_track(recognize_images([img]))
    assert notes_of(track) == [[[(0, 3)]] * 4, [[(0, 5)]] * 4]
    vib = [[b.notes[0].vibrato for b in m.beats] for m in track.measures]
    assert vib == [[False] * 4, [False, False, True, False]]
