"""FICTIONAL specifications used as sample PDFs: one for buildings, one for electrical installations.

It is written to look like a real spec (numbered clauses, cross-references,
distracting similar clauses) but it is NOT a real building code.

Each spec has RULES (machine-readable numeric clauses, used by the eval to compute
ground-truth PASS/FAIL answers), SECTIONS (the text), QA pairs and out-of-scope questions.
SPECS at the bottom maps a spec name to all of that.
"""
from __future__ import annotations

from pathlib import Path

BUILDING_RULES = {
    "corridor_min_width_mm": 1100,          # clause 3.2
    "door_min_width_mm": 800,               # clause 4.1 (habitable rooms)
    "bath_door_min_width_mm": 750,          # clause 4.2
    "min_area_m2": {"BEDROOM": 9.5, "LIVING": 13.0, "KITCHEN": 5.5, "STUDY": 6.5},  # 5.1-5.4
    "habitable_needs_window": True,         # clause 6.1
}

BUILDING_SECTIONS: list[dict] = [
    {"title": "1 General", "clauses": [
        ("1.1", "This specification sets out minimum design requirements for single-storey residential "
                "units submitted for review. It applies to new construction and to major renovations."),
        ("1.2", "All drawings shall be submitted in DXF format with dimensions in millimetres. Areas in "
                "this specification are expressed in square metres measured to the centre-line of walls."),
        ("1.3", "Where a requirement in this specification conflicts with a local regulation, the more "
                "stringent requirement applies. The reviewing engineer may grant written exemptions."),
        ("1.4", "Terms: a habitable room is a living room, bedroom, study or kitchen. Bathrooms, stores "
                "and corridors are non-habitable spaces."),
    ]},
    {"title": "2 Drawing Standards", "clauses": [
        ("2.1", "Walls shall be drawn on layer WALLS. Room boundaries shall be closed polylines on layer "
                "ROOMS, with the room name as a text entity placed inside the boundary on layer ROOM_NAMES."),
        ("2.2", "Doors shall be inserted as blocks on layer DOORS, scaled so that the block width equals "
                "the clear opening width. Windows shall be drawn on layer WINDOWS along the external wall."),
        ("2.3", "Every plan shall carry overall dimensions on layer DIMENSIONS and a title block stating "
                "the plan reference, scale and units on layer ANNOTATION."),
        ("2.4", "Line weights, text heights and colours are at the designer's discretion provided the "
                "drawing remains legible when printed at A3."),
    ]},
    {"title": "3 Corridors and Circulation", "clauses": [
        ("3.1", "Circulation routes shall be continuous and free of steps. Floor finishes in corridors "
                "shall be slip resistant."),
        ("3.2", "The clear width of any internal corridor shall be not less than 1100 mm, measured "
                "between wall centre-lines."),
        ("3.3", "Corridors shall be provided with artificial lighting achieving at least 100 lux at "
                "floor level, with switching at each end of the corridor."),
        ("3.4", "The travel distance from the door of any habitable room to the unit's main exit shall "
                "not exceed 18 metres."),
    ]},
    {"title": "4 Doors", "clauses": [
        ("4.1", "Doors serving habitable rooms shall provide a clear opening width of not less than 800 mm."),
        ("4.2", "Doors to bathrooms and stores shall provide a clear opening width of not less than 750 mm."),
        ("4.3", "Door hardware shall be lever-operated and mounted between 900 mm and 1050 mm above "
                "finished floor level."),
        ("4.4", "Bathroom doors shall be capable of being opened from outside in an emergency."),
    ]},
    {"title": "5 Room Sizes", "clauses": [
        ("5.1", "Each bedroom shall have a floor area of not less than 9.5 square metres."),
        ("5.2", "The living room shall have a floor area of not less than 13.0 square metres."),
        ("5.3", "The kitchen shall have a floor area of not less than 5.5 square metres, with a "
                "continuous worktop of at least 2 metres."),
        ("5.4", "A study, where provided, shall have a floor area of not less than 6.5 square metres."),
        ("5.5", "No habitable room shall have any internal dimension smaller than 2100 mm."),
    ]},
    {"title": "6 Daylight and Ventilation", "clauses": [
        ("6.1", "Every habitable room shall have at least one window in an external wall."),
        ("6.2", "The glazed area of windows serving a habitable room should be at least 10 percent of "
                "the floor area of that room."),
        ("6.3", "Bathrooms without a window shall be provided with mechanical extract ventilation "
                "rated at not less than 15 litres per second."),
        ("6.4", "Kitchens shall have mechanical extract over the cooking area in addition to any window."),
    ]},
    {"title": "7 Fire Safety", "clauses": [
        ("7.1", "A mains-powered smoke alarm with battery backup shall be installed in the corridor and "
                "in the living room."),
        ("7.2", "A heat alarm shall be installed in the kitchen. Smoke alarms shall not be installed in kitchens."),
        ("7.3", "Internal doors on the escape route shall be self-closing where the unit exceeds 100 "
                "square metres in total floor area."),
    ]},
    {"title": "8 Submission and Review", "clauses": [
        ("8.1", "Submissions shall include the DXF drawing, this checklist completed by the designer, "
                "and a schedule of room areas."),
        ("8.2", "The reviewer will respond within 10 working days. Non-compliant items will be listed "
                "with the clause number they fail."),
        ("8.3", "A resubmission addressing all listed items will be reviewed within 5 working days."),
    ]},
]

HABITABLE_TYPES = ("LIVING", "BEDROOM", "STUDY", "KITCHEN")  # clause 1.4

# Paraphrased questions (not copied wording) -> the clause that answers them.
BUILDING_QA: list[tuple[str, str]] = [
    ("What is the minimum width allowed for a corridor?", "3.2"),
    ("How wide must hallways be inside the unit?", "3.2"),
    ("How bright must corridor lighting be?", "3.3"),
    ("What is the maximum distance from a bedroom door to the exit?", "3.4"),
    ("Can a corridor have steps in it?", "3.1"),
    ("What clear opening is required for a bedroom door?", "4.1"),
    ("How wide must a bathroom door be?", "4.2"),
    ("At what height should door handles be fitted?", "4.3"),
    ("Must a bathroom door be openable from the outside?", "4.4"),
    ("What is the smallest permitted bedroom size?", "5.1"),
    ("How big must the living room be?", "5.2"),
    ("What is the minimum kitchen floor area?", "5.3"),
    ("How long must the kitchen worktop be?", "5.3"),
    ("Minimum area for a study room?", "5.4"),
    ("What is the smallest internal dimension a habitable room can have?", "5.5"),
    ("Does every habitable room need a window?", "6.1"),
    ("How much glazing is needed relative to floor area?", "6.2"),
    ("What ventilation is required for a bathroom with no window?", "6.3"),
    ("Where must smoke alarms be installed?", "7.1"),
    ("What kind of alarm goes in the kitchen?", "7.2"),
    ("When do escape route doors need to be self-closing?", "7.3"),
    ("Which layer should walls be drawn on?", "2.1"),
    ("How should doors be represented in the drawing?", "2.2"),
    ("What must the title block contain?", "2.3"),
    ("What file format should drawings be submitted in?", "1.2"),
    ("Which rooms count as habitable?", "1.4"),
    ("What happens when this spec conflicts with local rules?", "1.3"),
    ("How long does the reviewer take to respond?", "8.2"),
    ("What documents are needed for a submission?", "8.1"),
    ("How quickly is a resubmission reviewed?", "8.3"),
]

# Out-of-scope questions: the system should say it cannot find an answer.
BUILDING_UNANSWERABLE = [
    "What is the required roof pitch?",
    "What colour should the front door be painted?",
    "What is the maximum height of a boundary fence?",
]



# =============================================================================
# Electrical installation specification
# =============================================================================
CABLE_CAPACITY_A = {1.5: 16, 2.5: 25, 4.0: 32, 6.0: 40, 10.0: 50}   # clause 3.1
CABLE_MAX_LENGTH_M = {1.5: 25, 2.5: 35, 4.0: 45, 6.0: 55, 10.0: 70}  # clause 6.2

ELECTRICAL_RULES = {
    "cable_capacity_a": CABLE_CAPACITY_A,       # 3.1 breaker rating <= cable capacity
    "lighting_max_breaker_a": 10,               # 3.2
    "main_min_rating_a": 63,                    # 3.3
    "load_factor": 0.8, "voltage_v": 230,       # 4.1 load <= 0.8 * rating * 230
    "lighting_max_points": 10,                  # 4.2
    "socket_max_points": 8,                     # 4.3
    "rcd_max_ma_for_sockets": 30,               # 5.1
    "cable_max_length_m": CABLE_MAX_LENGTH_M,   # 6.2
}

ELECTRICAL_SECTIONS: list[dict] = [
    {"title": "1 General", "clauses": [
        ("1.1", "This specification covers low-voltage final circuits in residential and small commercial "
                "buildings supplied at 230 V single phase."),
        ("1.2", "Schematics shall be submitted in DXF format. Devices and loads shall be drawn as blocks "
                "carrying the attributes TAG, RATING_A, SIZE_SQMM, LENGTH_M, LOAD_W and SENS_MA as applicable."),
        ("1.3", "Terms: a final circuit is the circuit from a miniature circuit breaker (MCB) to the loads it "
                "supplies. A lighting circuit supplies luminaires; a socket circuit supplies socket outlets."),
    ]},
    {"title": "2 Drawing Conventions", "clauses": [
        ("2.1", "Conductors shall be drawn on layer WIRES and the distribution busbar on layer BUSBAR."),
        ("2.2", "Every device shall carry a unique tag. Final circuits shall be numbered C1, C2, C3 and so on "
                "from left to right."),
        ("2.3", "The title block shall state the board reference, the supply voltage and the drawing revision."),
    ]},
    {"title": "3 Protective Devices", "clauses": [
        ("3.1", "The rating of a circuit breaker shall not exceed the current-carrying capacity of the cable it "
                "protects. Capacities: 1.5 sq mm cable 16 A; 2.5 sq mm cable 25 A; 4 sq mm cable 32 A; "
                "6 sq mm cable 40 A; 10 sq mm cable 50 A."),
        ("3.2", "Lighting circuits shall be protected by breakers rated not more than 10 A."),
        ("3.3", "The main switch of a distribution board shall be rated not less than 63 A."),
        ("3.4", "Type B breakers shall be used for lighting and socket circuits. Type C breakers shall be used "
                "for motor and compressor loads."),
    ]},
    {"title": "4 Circuit Loading", "clauses": [
        ("4.1", "The connected load of a final circuit shall not exceed 80 percent of the breaker rating "
                "multiplied by 230 V."),
        ("4.2", "A lighting circuit shall supply not more than 10 luminaires."),
        ("4.3", "A socket circuit shall supply not more than 8 socket outlets."),
        ("4.4", "Air conditioners and water heaters shall each be supplied by a dedicated circuit serving no "
                "other load."),
    ]},
    {"title": "5 Earth Leakage Protection", "clauses": [
        ("5.1", "Every circuit supplying socket outlets shall be protected by a residual current device (RCD) "
                "with a rated residual operating current not exceeding 30 mA."),
        ("5.2", "RCDs shall be tested by the occupier using the test button every three months."),
        ("5.3", "Water heater circuits should be RCD protected where the heater is in a bathroom."),
    ]},
    {"title": "6 Cables", "clauses": [
        ("6.1", "Cables shall have copper conductors with PVC insulation rated for 70 degrees Celsius."),
        ("6.2", "To limit voltage drop, cable run lengths shall not exceed: 1.5 sq mm 25 m; 2.5 sq mm 35 m; "
                "4 sq mm 45 m; 6 sq mm 55 m; 10 sq mm 70 m."),
        ("6.3", "The minimum cable size is 1.5 sq mm for lighting circuits and 2.5 sq mm for socket circuits."),
    ]},
    {"title": "7 Earthing and Bonding", "clauses": [
        ("7.1", "Each installation shall have a main earthing terminal connected to the supply earth."),
        ("7.2", "Metal water and gas pipes shall be bonded to the main earthing terminal within 600 mm of "
                "their point of entry."),
    ]},
    {"title": "8 Testing and Handover", "clauses": [
        ("8.1", "Insulation resistance between live conductors and earth shall be not less than 1 megohm."),
        ("8.2", "On completion the installer shall hand over a test certificate and a labelled circuit "
                "schedule fixed inside the distribution board door."),
    ]},
]

ELECTRICAL_QA: list[tuple[str, str]] = [
    ("What breaker size is allowed for a 2.5 sq mm cable?", "3.1"),
    ("What is the maximum breaker rating for lighting circuits?", "3.2"),
    ("What is the smallest permitted main switch rating?", "3.3"),
    ("Which breaker curve should be used for motors?", "3.4"),
    ("How much load can a final circuit carry relative to its breaker?", "4.1"),
    ("How many light fittings can one lighting circuit feed?", "4.2"),
    ("What is the limit on socket outlets per circuit?", "4.3"),
    ("Can an air conditioner share a circuit with other loads?", "4.4"),
    ("What earth leakage protection do socket circuits need?", "5.1"),
    ("How often should RCDs be tested?", "5.2"),
    ("What conductor material should cables use?", "6.1"),
    ("What is the longest allowed run for 1.5 sq mm cable?", "6.2"),
    ("What is the minimum cable size for sockets?", "6.3"),
    ("What must metal water pipes be connected to?", "7.2"),
    ("What insulation resistance is acceptable?", "8.1"),
    ("Which layer are conductors drawn on?", "2.1"),
    ("What supply voltage does this specification cover?", "1.1"),
    ("What is meant by a final circuit?", "1.3"),
    ("What documents are handed over after testing?", "8.2"),
    ("How must circuits be numbered?", "2.2"),
]

ELECTRICAL_UNANSWERABLE = [
    "What tilt angle is required for solar panels?",
    "Which brand of breaker must be used?",
    "What colour should the board enclosure be painted?",
]

SPECS: dict[str, dict] = {
    "building": {
        "file": "building_spec.pdf",
        "title": "Sample Residential Design Specification",
        "sections": BUILDING_SECTIONS, "rules": BUILDING_RULES,
        "qa": BUILDING_QA, "unanswerable": BUILDING_UNANSWERABLE,
    },
    "electrical": {
        "file": "electrical_spec.pdf",
        "title": "Sample Electrical Installation Specification",
        "sections": ELECTRICAL_SECTIONS, "rules": ELECTRICAL_RULES,
        "qa": ELECTRICAL_QA, "unanswerable": ELECTRICAL_UNANSWERABLE,
    },
}
SUBTITLE = "FICTIONAL DOCUMENT - created for testing CAD Copilot. Not a real code or standard."

# Backwards-compatible names (building spec)
RULES, SECTIONS, SPEC_QA, UNANSWERABLE = BUILDING_RULES, BUILDING_SECTIONS, BUILDING_QA, BUILDING_UNANSWERABLE


def build_spec_pdf(path: str | Path, spec: str = "building") -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    cfg = SPECS[spec]
    styles = getSampleStyleSheet()
    body = ParagraphStyle("clause", parent=styles["BodyText"], fontSize=10.5, leading=15, spaceAfter=8)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm,
                            topMargin=20 * mm, bottomMargin=20 * mm, title=cfg["title"])
    story = [Paragraph(cfg["title"], styles["Title"]), Paragraph(f"<i>{SUBTITLE}</i>", styles["Normal"]),
             Spacer(1, 10)]
    for i, sec in enumerate(cfg["sections"]):
        # Two sections per page so page citations are meaningful.
        if i and i % 2 == 0:
            story.append(PageBreak())
        story.append(Paragraph(sec["title"], styles["Heading2"]))
        for cid, text in sec["clauses"]:
            story.append(Paragraph(f"<b>{cid}</b> {text}", body))
    doc.build(story)
    return Path(path)
