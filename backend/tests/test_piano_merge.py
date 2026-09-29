import xml.etree.ElementTree as ET

from app.piano.merge import merge


def note(step: str, octave: int, staff: int = 1, dur: int = 4, voice: int = 1) -> str:
    return (
        f"<note><pitch><step>{step}</step><octave>{octave}</octave></pitch>"
        f"<duration>{dur}</duration><voice>{voice}</voice><type>whole</type>"
        f"<staff>{staff}</staff></note>"
    )


def attrs(fifths=0, beats=4, divisions=1, clefs=(("G", 2), ("F", 4)), staves=2) -> str:
    clef = "".join(
        f'<clef number="{i + 1}"><sign>{s}</sign><line>{ln}</line></clef>'
        for i, (s, ln) in enumerate(clefs)
    )
    return (
        f"<attributes><divisions>{divisions}</divisions><staves>{staves}</staves>"
        f"<part-symbol>brace</part-symbol></attributes>"
        f"<attributes><key><fifths>{fifths}</fifths></key>"
        f"<time><beats>{beats}</beats><beat-type>4</beat-type></time>{clef}</attributes>"
    )


def system(*measures: str, parts: int = 1) -> str:
    body = "".join(f'<measure number="{i + 1}">{m}</measure>' for i, m in enumerate(measures))
    part_list = "".join(
        f'<score-part id="P{p + 1}"><part-name>Piano</part-name></score-part>' for p in range(parts)
    )
    part = "".join(f'<part id="P{p + 1}">{body}</part>' for p in range(parts))
    return (
        '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="4.0">'
        f"<part-list>{part_list}</part-list>{part}</score-partwise>"
    )


def two_hands(first_attrs: str = "") -> str:
    return first_attrs + note("C", 5) + "<backup><duration>4</duration></backup>" + note("C", 3, 2)


def parse(xml: str):
    root = ET.fromstring(xml)
    parts = root.findall("part")
    assert len(parts) == 1
    assert len(root.findall("part-list/score-part")) == 1
    return root, parts[0].findall("measure")


def test_measures_are_numbered_on_from_one_and_nothing_is_repeated():
    a = system(two_hands(attrs()), two_hands())
    b = system(two_hands(attrs()), two_hands())
    root, measures = parse(merge([a, b]))
    assert [m.get("number") for m in measures] == ["1", "2", "3", "4"]
    assert len(root.findall(".//key")) == 1
    assert len(root.findall(".//time")) == 1
    assert len(root.findall(".//clef")) == 2  # one per staff
    assert len(root.findall(".//divisions")) == 1
    assert len(root.findall(".//staves")) == 1
    assert len(root.findall(".//part-symbol")) == 1
    assert not measures[2].findall("attributes")  # emptied attributes are removed
    assert len(root.findall(".//note")) == 8
    # each system starts on a new line, like in the video
    assert measures[2].find("print").get("new-system") == "yes"
    assert measures[0].find("print") is None


def test_changes_between_systems_are_kept():
    a = system(two_hands(attrs()))
    b = system(two_hands(attrs(fifths=-4, beats=2, divisions=2, clefs=(("G", 2), ("G", 2)))))
    root, measures = parse(merge([a, b]))
    second = measures[1]
    assert second.find(".//key/fifths").text == "-4"
    assert second.find(".//time/beats").text == "2"
    assert second.find(".//divisions").text == "2"
    clefs = second.findall(".//clef")
    assert [(c.get("number"), c.findtext("sign")) for c in clefs] == [("2", "G")]


def test_a_clef_change_inside_a_system_carries_into_the_next_one():
    change = '<attributes><clef number="2"><sign>G</sign><line>2</line></clef></attributes>'
    a = system(two_hands(attrs()) + change)
    b = system(two_hands(attrs(clefs=(("G", 2), ("G", 2)))))
    root, measures = parse(merge([a, b]))
    assert len(measures[1].findall(".//clef")) == 0


def test_systems_read_as_two_single_staff_parts_become_one_grand_staff():
    one_staff = attrs(clefs=(("G", 2),), staves=1)
    a = system(one_staff + note("E", 5), note("F", 5), parts=2)
    root, measures = parse(merge([a]))
    assert len(measures) == 2
    staffs = [n.findtext("staff") for n in measures[1].findall("note")]
    assert staffs == ["1", "2"]
    assert measures[0].find(".//staves").text == "2"


def test_empty_or_broken_systems_are_skipped():
    a = system(two_hands(attrs()))
    root, measures = parse(merge(["", "<not-xml", a, system()]))
    assert len(measures) == 1
    assert measures[0].find("print") is None
