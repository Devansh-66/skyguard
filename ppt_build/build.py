"""Fill the SIH 2026 Idea template without altering its format.

The template's own instruction slide says the deck must use the provided
template "without changing the idea details pointers". So every pointer line
("Detailed explanation of the proposed solution", "Potential challenges and
risks", ...) is kept VERBATIM as a bold lead-in, and our material goes
underneath it as sub-bullets. Nothing the template asks for is removed or
reworded, and no slide, placeholder, logo or footer is moved or restyled.

This is an IDEA submission, so it describes the proposed solution only. No
implementation progress and no measured results appear anywhere in the deck.

Paragraph XML is built from the template's own run properties (Arial, scheme
colours, Wingdings/Arial bullets) so the styling is inherited rather than
reinvented. The only geometry changes are vertical positions of the content
text boxes, which the template leaves as free-floating text boxes rather than
layout placeholders, and which have to move because our content is longer than
the one-line prompts they shipped with.
"""
import re
import zipfile

SRC = "SIH2026-IDEA-Presentation-Format.pptx"
OUT = "SkyGuard-SIH2026-Idea.pptx"
EMU = 914400

ARIAL = ('<a:latin typeface="Arial" pitchFamily="34" charset="0"/>'
         '<a:cs typeface="Arial" pitchFamily="34" charset="0"/>')
BUL_ARIAL = ('<a:buFont typeface="Arial" panose="020B0604020202020204" '
             'pitchFamily="34" charset="0"/><a:buChar char="•"/>')
BUL_DASH = ('<a:buFont typeface="Arial" panose="020B0604020202020204" '
            'pitchFamily="34" charset="0"/><a:buChar char="–"/>')
BUL_WING = ('<a:buFont typeface="Wingdings" panose="05000000000000000000" '
            'pitchFamily="2" charset="2"/><a:buChar char="v"/>')
TX2 = '<a:solidFill><a:schemeClr val="tx2"/></a:solidFill>'


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def para(text, sz, *, bold=False, uline=False, level=0, bullet="arial",
         color=False, space_before=0):
    bu = {"arial": BUL_ARIAL, "dash": BUL_DASH, "wing": BUL_WING,
          "none": "<a:buNone/>"}[bullet]
    marL, ind = (342900, -342900) if level == 0 else (742950, -285750)
    sp = f'<a:spcBef><a:spcPts val="{space_before}"/></a:spcBef>' if space_before else ""
    rpr = (f'<a:rPr lang="en-US" sz="{sz}"'
           + (' b="1"' if bold else "") + (' u="sng"' if uline else "")
           + ' dirty="0">' + (TX2 if color else "") + ARIAL + "</a:rPr>")
    return (f'<a:p><a:pPr marL="{marL}" indent="{ind}" algn="just">{sp}{bu}</a:pPr>'
            f"<a:r>{rpr}<a:t>{esc(text)}</a:t></a:r></a:p>")


def build(blocks, heading=None, head_sz=2000, ptr_sz=1600, body_sz=1300):
    out = []
    if heading:
        out.append(para(heading, head_sz, bold=True, uline=True,
                        bullet="wing", color=True))
    for pointer, children in blocks:
        out.append(para(pointer, ptr_sz, bold=True, color=True, space_before=600))
        for c in children:
            out.append(para(c, body_sz, level=1, bullet="dash"))
    return "".join(out)


def _shape(xml, name):
    m = re.search(r'<p:sp>(?:(?!</p:sp>).)*?name="%s".*?</p:sp>' % re.escape(name),
                  xml, re.S)
    if not m:
        raise SystemExit(f"shape {name!r} not found")
    return m


def replace_body(xml, name, body_xml):
    m = _shape(xml, name)
    sp = re.sub(r"(<a:lstStyle/>).*?(</p:txBody>)",
                lambda mm: mm.group(1) + body_xml + mm.group(2), m.group(0), flags=re.S)
    return xml[:m.start()] + sp + xml[m.end():]


def move(xml, name, y=None, x=None, cy=None, cx=None):
    """Reposition one shape. Only <a:off>/<a:ext> numbers change."""
    m = _shape(xml, name)
    sp = m.group(0)
    o = re.search(r'<a:off x="(-?\d+)" y="(-?\d+)"/><a:ext cx="(\d+)" cy="(\d+)"/>', sp)
    if not o:
        raise SystemExit(f"{name}: no xfrm to move")
    X, Y, CX, CY = (int(v) for v in o.groups())
    new = (f'<a:off x="{x if x is not None else X}" y="{y if y is not None else Y}"/>'
           f'<a:ext cx="{cx if cx is not None else CX}" '
           f'cy="{cy if cy is not None else CY}"/>')
    sp = sp[:o.start()] + new + sp[o.end():]
    return xml[:m.start()] + sp + xml[m.end():]


def set_runs(xml, name, texts, size=None):
    m = _shape(xml, name)
    sp, it = m.group(0), iter(texts)

    def sub(mm):
        try:
            return "<a:t>" + esc(next(it)) + "</a:t>"
        except StopIteration:
            return mm.group(0)
    sp = re.sub(r"<a:t>.*?</a:t>", sub, sp, flags=re.S)
    if size:
        sp = re.sub(r'sz="\d+"', f'sz="{size}"', sp)
    return xml[:m.start()] + sp + xml[m.end():]


# ------------------------------------------------------- flow diagram (slide 3)

def flow(steps, y_in=4.72, h_in=1.05, left_in=0.72, right_in=0.72):
    """A left-to-right chain of rounded boxes with arrows between them.

    Built as ordinary DrawingML shapes appended to the slide's shape tree, so
    the template's own placeholders, logo and footer are untouched.
    """
    total = 13.333 - left_in - right_in
    gap = 0.30
    bw = (total - gap * (len(steps) - 1)) / len(steps)
    xml, sid = [], 900
    for i, (head, sub) in enumerate(steps):
        x = left_in + i * (bw + gap)
        sid += 1
        body = (
            '<a:p><a:pPr algn="ctr"><a:buNone/></a:pPr>'
            f'<a:r><a:rPr lang="en-US" sz="1050" b="1" dirty="0">'
            '<a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>'
            f'{ARIAL}</a:rPr><a:t>{esc(head)}</a:t></a:r></a:p>'
            '<a:p><a:pPr algn="ctr"><a:buNone/></a:pPr>'
            f'<a:r><a:rPr lang="en-US" sz="900" dirty="0">'
            '<a:solidFill><a:srgbClr val="D6E4F0"/></a:solidFill>'
            f'{ARIAL}</a:rPr><a:t>{esc(sub)}</a:t></a:r></a:p>')
        xml.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="Flow {i+1}"/>'
            '<p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm>'
            f'<a:off x="{int(x*EMU)}" y="{int(y_in*EMU)}"/>'
            f'<a:ext cx="{int(bw*EMU)}" cy="{int(h_in*EMU)}"/></a:xfrm>'
            '<a:prstGeom prst="roundRect"><a:avLst>'
            '<a:gd name="adj" fmla="val 14000"/></a:avLst></a:prstGeom>'
            f'<a:solidFill><a:srgbClr val="{"1F4E79" if i == 0 else "2E75B6"}"/>'
            '</a:solidFill><a:ln><a:noFill/></a:ln></p:spPr>'
            '<p:txBody><a:bodyPr lIns="54000" rIns="54000" tIns="45720" '
            'bIns="45720" anchor="ctr" wrap="square"><a:normAutofit/></a:bodyPr>'
            f"<a:lstStyle/>{body}</p:txBody></p:sp>")
        if i < len(steps) - 1:
            sid += 1
            ax = x + bw + 0.045
            xml.append(
                f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="Arrow {i+1}"/>'
                '<p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm>'
                f'<a:off x="{int(ax*EMU)}" y="{int((y_in+h_in/2-0.085)*EMU)}"/>'
                f'<a:ext cx="{int((gap-0.09)*EMU)}" cy="{int(0.17*EMU)}"/></a:xfrm>'
                '<a:prstGeom prst="rightArrow"><a:avLst/></a:prstGeom>'
                '<a:solidFill><a:srgbClr val="9AB7D3"/></a:solidFill>'
                '<a:ln><a:noFill/></a:ln></p:spPr><p:txBody><a:bodyPr/>'
                "<a:lstStyle/><a:p><a:endParaRPr lang=\"en-US\"/></a:p>"
                "</p:txBody></p:sp>")
    return "".join(xml)


# --------------------------------------------------------------- the content

TITLE_LINES = [
    "Problem Statement ID – PS26073",
    "Problem Statement Title– AI/ML based anomaly detection in Automatic "
    "Weather Station data",
    "Theme– <THEME AS LISTED ON THE SIH PORTAL>",
    "PS Category- Software",
    "Team ID– <TEAM ID>",
    "Team Name (Registered on portal)– <TEAM NAME>",
]

S2 = build([
    ("Detailed explanation of the proposed solution", [
        "Four stages: remove the expected daily and seasonal cycle, compare the "
        "station against its nearest neighbours, score what is left with an "
        "unsupervised model, then name the likely fault from its shape.",
        "Uses only the three fields the problem statement provides — temperature, "
        "pressure and relative humidity. No extra instrument is assumed.",
        "Two tiers: a physical-plausibility screen on the station node itself, and "
        "everything that needs neighbouring stations on one server.",
    ]),
    ("How it addresses the problem", [
        "Separates a faulty sensor from real weather by asking whether the "
        "neighbouring stations moved in the same direction at the same time.",
        "Every alert names a probable cause with a confidence — stuck probe, "
        "drift, step offset, dropout — instead of raising a bare flag.",
        "Alert volume is held to a fixed budget per station per week, so the output "
        "stays small enough for an operator to actually read.",
    ]),
    ("Innovation and uniqueness of the solution", [
        "The baseline is frozen on an approved reference window and never refitted "
        "on live data: a self-updating baseline quietly absorbs slow drift and "
        "hides the very fault it should expose.",
        "Dew point is used as a physical cross-check — heating a probe raises "
        "temperature and lowers humidity but leaves dew point where it was, which "
        "separates a shield or siting fault from genuinely warmer air.",
        "Answering “unknown” when the evidence supports no cause is a designed "
        "output, not a failure.",
    ]),
], heading="Proposed Solution (Describe your Idea/Solution/Prototype)")

S3 = build([
    ("Technologies to be used (e.g. programming languages, frameworks, hardware)", [
        "Python — NumPy, pandas and scikit-learn for the residual, detection and "
        "classification stages. No GPU and no model server.",
        "FastAPI service with a browser operator console; Leaflet map on satellite "
        "imagery with the official India boundary served by NCMRWF (MoES).",
        "Station node: ESP32-class microcontroller with a BME280 temperature / "
        "pressure / humidity sensor. PostgreSQL with TimescaleDB for storage.",
    ]),
    ("Methodology and process for implementation (Flow Charts/Images/ working prototype)", [
        "The station tier holds only constant-size state, so no history buffer or "
        "model runtime is needed on the node; thresholds are calibrated on a clean "
        "reference period before deployment.",
    ]),
], body_sz=1250)

S4 = build([
    ("Analysis of the feasibility of the idea", [
        "A national network at 15-minute reporting is only a few records per "
        "second — one modest on-premise VM handles it with no GPU.",
        "Methods are established and inspectable: robust regression, neighbour "
        "differencing, unsupervised scoring. Not a black box.",
        "The station tier is inexpensive and runs on hardware already common in "
        "AWS deployments.",
    ]),
    ("Potential challenges and risks", [
        "Station density — neighbour comparison only works where a nearby "
        "station is correlated enough to serve as a reference.",
        "Genuine severe weather can look like a fault, risking false alarms during "
        "exactly the events that matter most.",
        "Slow calibration drift never looks like an outlier at any single moment.",
        "Alert fatigue: a system that flags too much gets switched off.",
    ]),
    ("Strategies", [
        "Measure how inter-station differences grow with distance first, and let "
        "that measurement choose each station's neighbours.",
        "Gate alerts on neighbour agreement, so a change the whole region shares "
        "reads as weather rather than a fault.",
        "Freeze the baseline on approved data and track drift as a divergence "
        "growing over days, never from a single reading.",
        "Cap alerts to a fixed budget per station-week, and abstain when uncertain.",
    ]),
], body_sz=1250)

S5 = build([
    ("Potential impact on the target audience", [
        "IMD and MoES network operators get a ranked, named list of the stations "
        "needing attention, instead of raw observation streams to inspect.",
        "Forecasting and numerical weather prediction gain cleaner input: bad "
        "observations are caught before they are assimilated.",
        "Field maintenance is directed to the station that is actually faulty, and "
        "to the sensor within it.",
    ]),
    ("Benefits of the solution (social, economic, environmental, etc.)", [
        "Social — warnings and forecasts that reach the public rest on "
        "observations checked for sensor faults.",
        "Economic — fewer wasted site visits, and instrument replacement planned "
        "from evidence of degradation rather than a fixed cycle.",
        "Environmental — the node transmits only flagged readings and a periodic "
        "health summary; radio transmission dominates an AWS power budget, so a "
        "quieter uplink means a smaller power system.",
        "Institutional — a long-term record whose quality is documented, which "
        "matters for climate-scale reuse of the archive.",
    ]),
])

S6 = build([
    ("Details / Links of the reference and research work", [
        "IMD — M. N. Ranalkar et al., “Quality control of Automatic Weather "
        "Station data”, MAUSAM 66(1), 2015: the checks IMD applies today, "
        "including the spatial regression test.",
        "IMD Vision 2047 (press release, 14 Jan 2025) — smart weather stations, "
        "AI for real-time quality control, and self-diagnosing instruments: "
        "internal.imd.gov.in/press_release/20250114_pr_3552.pdf",
        "NCMRWF Technical Report NMRF/TR/02/2022 — observation quality control "
        "and buddy checks in the operational assimilation system.",
        "NCMRWF operational dashboard and model guidance: nwp.ncmrwf.gov.in",
        "WMO-No. 8, Guide to Instruments and Methods of Observation (CIMO Guide) "
        "— measurement uncertainty and siting classification.",
        "ECMWF ERA5 reanalysis via the Copernicus Climate Data Store — reference "
        "fields used to develop and test the method.",
    ]),
])

FLOW = [
    ("STATION NODE", "range · rate · stuck-value screen"),
    ("REMOVE CYCLE", "frozen daily + seasonal baseline"),
    ("COMPARE NEIGHBOURS", "did nearby stations move too?"),
    ("SCORE", "unsupervised, fixed alert budget"),
    ("NAME + EXPLAIN", "cause, confidence, or “unknown”"),
]

# ------------------------------------------------------------------- assemble

zin = zipfile.ZipFile(SRC)
names = zin.namelist()
data = {n: zin.read(n) for n in names}
zin.close()

s1 = data["ppt/slides/slide1.xml"].decode("utf8")
s1 = set_runs(s1, "TextBox 9", TITLE_LINES, size=1600)
# 200 % line spacing was set for one-line prompts; our filled lines wrap, so it
# is brought back to 130 % or the six required fields do not fit the slide.
s1 = s1.replace('<a:lnSpc><a:spcPct val="200000"/></a:lnSpc>',
                '<a:lnSpc><a:spcPct val="130000"/></a:lnSpc>')
data["ppt/slides/slide1.xml"] = s1.encode("utf8")

s2 = data["ppt/slides/slide2.xml"].decode("utf8")
s2 = set_runs(s2, "Title 1", ["SKYGUARD: AWS DATA QUALITY CONTROL"], size=2800)
s2 = replace_body(s2, "TextBox 8", S2)
s2 = move(s2, "TextBox 8", y=int(1.72 * EMU))
data["ppt/slides/slide2.xml"] = s2.encode("utf8")

s3 = data["ppt/slides/slide3.xml"].decode("utf8")
s3 = replace_body(s3, "TextBox 8", S3)
s3 = move(s3, "TextBox 8", y=int(1.52 * EMU), x=int(0.60 * EMU),
          cx=int(12.15 * EMU))
s3 = s3.replace("</p:spTree>", flow(FLOW) + "</p:spTree>")
data["ppt/slides/slide3.xml"] = s3.encode("utf8")

for n, body, ypos in ((4, S4, 1.42), (5, S5, 1.75), (6, S6, 1.95)):
    k = f"ppt/slides/slide{n}.xml"
    x = replace_body(data[k].decode("utf8"), "TextBox 8", body)
    x = move(x, "TextBox 8", y=int(ypos * EMU), x=int(0.60 * EMU),
             cx=int(12.15 * EMU))
    data[k] = x.encode("utf8")

# Drop slide 7. Its own text says to: "You can delete this slide (Important
# Pointers) when you upload", and the same slide caps the deck at six.
pres = data["ppt/presentation.xml"].decode("utf8")
ids = re.findall(r"<p:sldId [^>]*/>", pres)
last = ids[-1]
rid = re.search(r'r:id="(rId\d+)"', last).group(1)
data["ppt/presentation.xml"] = pres.replace(last, "").encode("utf8")

rels = data["ppt/_rels/presentation.xml.rels"].decode("utf8")
rel = re.search(r'<Relationship Id="%s"[^>]*/>' % rid, rels).group(0)
tgt = re.search(r'Target="([^"]+)"', rel).group(1).replace("slides/", "")
data["ppt/_rels/presentation.xml.rels"] = rels.replace(rel, "").encode("utf8")

ct = data["[Content_Types].xml"].decode("utf8")
ct = re.sub(r'<Override PartName="/ppt/slides/%s"[^>]*/>' % re.escape(tgt), "", ct)
data["[Content_Types].xml"] = ct.encode("utf8")

drop = {f"ppt/slides/{tgt}", f"ppt/slides/_rels/{tgt}.rels"}

# Whatever that slide owned outright goes with it. Its notes slide is the one
# that bites: leave it behind and it still points at a slide that no longer
# exists, which PowerPoint reports as a corrupt file.
srels = data.get(f"ppt/slides/_rels/{tgt}.rels")
if srels:
    for t in re.findall(r'Target="([^"]+)"', srels.decode("utf8")):
        if "notesSlide" in t:
            part = "ppt/" + t.replace("../", "")
            drop.add(part)
            drop.add(part.replace("notesSlides/", "notesSlides/_rels/") + ".rels")

ct = data["[Content_Types].xml"].decode("utf8")
for d in drop:
    ct = re.sub(r'<Override PartName="/%s"[^>]*/>' % re.escape(d), "", ct)
data["[Content_Types].xml"] = ct.encode("utf8")

names = [n for n in names if n not in drop]

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for n in names:
        z.writestr(n, data[n])

print(f"wrote {OUT}  ({len(names)} parts, removed {sorted(drop)})")
