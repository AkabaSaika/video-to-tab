"""Join the MusicXML of each system, in order, into one piano piece.

One part with two staves; measures numbered 1, 2, … across systems; a key, time signature,
clef or divisions that does not change from what is already in force is dropped, so it is
not repeated at every system. Each system after the first starts a new line."""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET

ORDER = ["divisions", "key", "time", "staves", "part-symbol", "clef"]


def _parse(xml: str) -> ET.Element | None:
    try:
        root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    except ET.ParseError:
        return None
    return root if root.tag == "score-partwise" else None


def _text(el: ET.Element) -> str:
    """A comparable form of an element: its tag, attributes and descendants' text."""
    return ET.tostring(el, encoding="unicode", short_empty_elements=True).replace(" ", "")


def _length(measure: ET.Element) -> int:
    pos = end = 0
    for el in measure:
        dur = int(el.findtext("duration") or 0)
        if el.tag == "note" and el.find("chord") is None and el.find("grace") is None:
            pos += dur
        elif el.tag == "backup":
            pos -= dur
        elif el.tag == "forward":
            pos += dur
        end = max(end, pos)
    return end


def _as_lower_staff(measure: ET.Element) -> list[ET.Element]:
    out = []
    for el in copy.deepcopy(measure):
        if el.tag == "note":
            staff = el.find("staff")
            if staff is None:
                staff = ET.SubElement(el, "staff")
            staff.text = "2"
            voice = el.find("voice")
            if voice is not None and (voice.text or "").isdigit():
                voice.text = str(int(voice.text) + 4)
        elif el.tag == "attributes":
            for clef in el.findall("clef"):
                clef.set("number", "2")
            for child in el.findall("staves") + el.findall("part-symbol"):
                el.remove(child)
        elif el.tag == "print":
            continue
        out.append(el)
    return out


def _measures(root: ET.Element) -> list[ET.Element]:
    """The system's measures as one two-staff part. homr writes one part with two staves
    for a grand staff; if it read the staves as two parts, the second becomes staff 2."""
    parts = root.findall("part")
    if not parts:
        return []
    upper = parts[0].findall("measure")
    if len(parts) < 2 or len(parts[1].findall("measure")) != len(upper):
        return upper
    lower = parts[1].findall("measure")
    for i, (m, low) in enumerate(zip(upper, lower, strict=True)):
        backup = ET.Element("backup")
        ET.SubElement(backup, "duration").text = str(_length(m))
        m.append(backup)
        m.extend(_as_lower_staff(low))
        if i == 0:
            attrs = m.find("attributes")
            if attrs is None:
                attrs = ET.Element("attributes")
                m.insert(0, attrs)
            staves = attrs.find("staves")
            if staves is None:
                staves = ET.Element("staves")
                attrs.insert(1 if attrs.find("divisions") is not None else 0, staves)
            staves.text = "2"
    return upper


def _key_of(el: ET.Element) -> str:
    return f"{el.tag}:{el.get('number', '')}"


def _drop_repeats(measure: ET.Element, state: dict[str, str]) -> None:
    for attrs in measure.findall("attributes"):
        for child in list(attrs):
            if child.tag not in ORDER:
                continue
            key = _key_of(child)
            value = _text(child)
            if (child.tag == "part-symbol" and key in state) or state.get(key) == value:
                attrs.remove(child)
            else:
                state[key] = value
        if len(attrs) == 0:
            measure.remove(attrs)


def merge(systems: list[str], title: str = "") -> str:
    """One MusicXML piece from the systems' MusicXML, in the given order. Systems that are
    empty or not MusicXML are skipped."""
    root = ET.Element("score-partwise", version="4.0")
    work = ET.SubElement(root, "work")
    ET.SubElement(work, "work-title").text = title
    ident = ET.SubElement(ET.SubElement(root, "identification"), "encoding")
    ET.SubElement(ident, "software").text = "video-to-tab (homr)"
    part_list = ET.SubElement(root, "part-list")
    score_part = ET.SubElement(part_list, "score-part", id="P1")
    ET.SubElement(score_part, "part-name").text = "Piano"
    part = ET.SubElement(root, "part", id="P1")
    state: dict[str, str] = {}
    number = 0
    for xml in systems:
        parsed = _parse(xml) if xml else None
        measures = _measures(parsed) if parsed is not None else []
        for i, m in enumerate(measures):
            number += 1
            m.attrib.pop("width", None)
            m.set("number", str(number))
            for old in m.findall("print"):
                m.remove(old)
            if i == 0 and number > 1:
                m.insert(0, ET.Element("print", {"new-system": "yes"}))
            _drop_repeats(m, state)
            part.append(m)
    ET.indent(root)
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"
