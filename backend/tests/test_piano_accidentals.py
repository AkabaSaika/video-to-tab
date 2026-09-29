import xml.etree.ElementTree as ET

from app.piano.accidentals import add_accidentals


def note(step, octave, alter=None, staff=1, tie_stop=False, accidental=None):
    alt = f"<alter>{alter}</alter>" if alter is not None else ""
    tie = '<tie type="stop"/>' if tie_stop else ""
    acc = f"<accidental>{accidental}</accidental>" if accidental else ""
    return (
        f"<note><pitch><step>{step}</step>{alt}<octave>{octave}</octave></pitch>"
        f"<duration>1</duration>{tie}<voice>1</voice><type>16th</type>{acc}"
        f"<staff>{staff}</staff></note>"
    )


def score(*measures, fifths=0):
    key = f"<attributes><key><fifths>{fifths}</fifths></key></attributes>"
    body = "".join(
        f'<measure number="{i + 1}">{key if i == 0 else ""}{m}</measure>'
        for i, m in enumerate(measures)
    )
    return f'<score-partwise version="4.0"><part id="P1">{body}</part></score-partwise>'


def accidentals(xml):
    root = ET.fromstring(add_accidentals(xml))
    return [
        [n.findtext("accidental") for n in m.findall("note")]
        for m in root.find("part").findall("measure")
    ]


def test_sharp_is_written_once_per_measure_and_again_in_the_next():
    xml = score(note("E", 5) + note("D", 5, 1) + note("D", 5, 1), note("D", 5, 1))
    assert accidentals(xml) == [[None, "sharp", None], ["sharp"]]


def test_natural_after_a_sharp_in_the_same_measure():
    xml = score(note("D", 5, 1) + note("D", 5))
    assert accidentals(xml) == [["sharp", "natural"]]


def test_key_signature_is_respected():
    # G major: F is sharp by key, so F# needs nothing and F natural needs a natural
    xml = score(note("F", 4, 1) + note("F", 4) + note("C", 4, -1), fifths=1)
    assert accidentals(xml) == [[None, "natural", "flat"]]


def test_octaves_and_staves_are_independent():
    xml = score(note("D", 5, 1) + note("D", 4, 1) + note("D", 5, 1, staff=2))
    assert accidentals(xml) == [["sharp", "sharp", "sharp"]]


def test_tied_continuation_and_existing_accidentals_are_left_alone():
    xml = score(
        note("G", 4, 1) + note("G", 4, 1, tie_stop=True), note("B", 4, -1, accidental="flat")
    )
    assert accidentals(xml) == [["sharp", None], ["flat"]]


def test_accidental_is_placed_where_musicxml_expects_it():
    root = ET.fromstring(add_accidentals(score(note("D", 5, 1))))
    tags = [c.tag for c in root.find("part/measure/note")]
    assert tags.index("accidental") == tags.index("type") + 1
