from __future__ import annotations
from flask import Flask, request, render_template, Response
from zoneinfo import ZoneInfo
import datetime as dt
import swisseph as swe
import math

app = Flask(__name__)

# ------------------ Config ------------------
DEFAULT_TZID = "America/New_York"
DEFAULT_USE_FIXED = True        # “No DST” style
DEFAULT_FIXED_UTC_OFFSET = -5.0 # hours (EST)
DEFAULT_CENTER = "geo"          # 'geo' or 'helio'
DEFAULT_HOUSE_SYS = "E"         # 'E' (Equal) or 'P' (Placidus)
DEFAULT_HOUSES_ORIENT = "ccw"   # 'ccw' or 'cw'
DEFAULT_ZODIAC_MODE = "tropical"  # 'tropical' or 'sidereal_fb'
DEFAULT_INCLUDE_NODES = True
DEFAULT_NODE_TYPE = "true"      # 'true' or 'mean'
DEFAULT_ORB = 6.0               # degrees (fallback)
DEFAULT_ORB_LIST = ""           # "8,5,6,6,8" for conj,sext,sqr,tri,opp

PLANETS = [
    ("Sun", swe.SUN), ("Moon", swe.MOON), ("Mercury", swe.MERCURY),
    ("Venus", swe.VENUS), ("Mars", swe.MARS), ("Jupiter", swe.JUPITER),
    ("Saturn", swe.SATURN), ("Uranus", swe.URANUS), ("Neptune", swe.NEPTUNE),
    ("Pluto", swe.PLUTO),
]

NODE_TYPES = {"true": swe.TRUE_NODE, "mean": swe.MEAN_NODE}

ASPECTS = [
    ("☌", 0),    # conjunction
    ("✶", 60),   # sextile
    ("□", 90),   # square
    ("△", 120),  # trine
    ("☍", 180),  # opposition
]

PLANET_GLYPHS = {
    "Sun": "☉", "Moon": "☽", "Mercury": "☿", "Venus": "♀",
    "Mars": "♂", "Jupiter": "♃", "Saturn": "♄", "Uranus": "♅",
    "Neptune": "♆", "Pluto": "♇", "North Node": "☊", "South Node": "☋"
}

SIGN_GLYPHS = ["♈︎","♉︎","♊︎","♋︎","♌︎","♍︎","♎︎","♏︎","♐︎","♑︎","♒︎","♓︎"]

# Holds last computed chart for /chart (simple, per-process memory)
LAST_CHART = {"rows": None, "zodiac_mode": DEFAULT_ZODIAC_MODE}

# ------------------ Helpers ------------------
def fmt_zodiac(deg: float) -> str:
    signs = [
        "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
        "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
    ]
    lon = deg % 360.0
    si = int(lon // 30)
    x = lon - si * 30
    d = int(x)
    m_full = (x - d) * 60
    m = int(m_full)
    s = int(round((m_full - m) * 60))
    if s == 60:
        s = 0; m += 1
    if m == 60:
        m = 0; d += 1
    return f"{d:02d}°{m:02d}'{s:02d}\" {signs[si]}"

def to_jd(local_date: str, local_time: str, tzid: str, use_fixed: bool, fixed_offset_h: float):
    local_dt = dt.datetime.strptime(f"{local_date} {local_time}", "%Y-%m-%d %H:%M")
    if use_fixed:
        tzinfo = dt.timezone(dt.timedelta(hours=float(fixed_offset_h)))
    else:
        tzinfo = ZoneInfo(tzid)
    local_dt = local_dt.replace(tzinfo=tzinfo)
    utc_dt = local_dt.astimezone(dt.timezone.utc)
    h = utc_dt.hour + utc_dt.minute/60 + utc_dt.second/3600
    jd = swe.julday(utc_dt.year, utc_dt.month, utc_dt.day, h)
    return jd, local_dt, utc_dt, (f"UTC{float(fixed_offset_h):+.0f} (fixed)" if use_fixed else tzid)

def compute_positions(jd_ut: float,
                      zodiac_mode: str,
                      center: str,
                      include_nodes: bool,
                      node_type: str):
    """Compute tropical + sidereal F/B, return table rows and ayanamsa used."""
    flags = 0
    if center == "helio":
        flags |= swe.FLG_HELCTR

    # Tropical longitudes
    trop = {}
    for name, code in PLANETS:
        vals, _ = swe.calc_ut(jd_ut, code, flags)
        trop[name] = float(vals[0]) % 360.0

    # Ayanamsa (Fagan/Bradley)
    swe.set_sid_mode(swe.SIDM_FAGAN_BRADLEY)
    ayan = swe.get_ayanamsa_ut(jd_ut)

    rows = []
    # Planets
    for name, _ in PLANETS:
        lt = trop[name]
        ls = (lt - ayan) % 360.0
        rows.append({
            "name": name,
            "trop": f"{lt:.6f}",
            "trop_sign": fmt_zodiac(lt),
            "sid": f"{ls:.6f}",
            "sid_sign": fmt_zodiac(ls),
        })

    # Nodes (geocentric only)
    if include_nodes and center != "helio":
        code = NODE_TYPES.get(node_type.lower(), swe.TRUE_NODE)
        nn_vals, _ = swe.calc_ut(jd_ut, code, 0)  # nodes computed geocentrically
        nn_trop = float(nn_vals[0]) % 360.0
        sn_trop = (nn_trop + 180.0) % 360.0
        nn_sid = (nn_trop - ayan) % 360.0
        sn_sid = (sn_trop - ayan) % 360.0
        rows.append({
            "name": "North Node",
            "trop": f"{nn_trop:.6f}",
            "trop_sign": fmt_zodiac(nn_trop),
            "sid": f"{nn_sid:.6f}",
            "sid_sign": fmt_zodiac(nn_sid),
        })
        rows.append({
            "name": "South Node",
            "trop": f"{sn_trop:.6f}",
            "trop_sign": fmt_zodiac(sn_trop),
            "sid": f"{sn_sid:.6f}",
            "sid_sign": fmt_zodiac(sn_sid),
        })

    return rows, ayan

def compute_houses(jd_ut: float, lat_deg: float, lon_deg: float, system_code: str = "E"):
    """Return dict with cusps, asc, mc. system_code: 'E' (Equal) or 'P' (Placidus)."""
    sys_char = b'E' if system_code.upper() == "E" else b'P'
    cusps, ascmc = swe.houses_ex(jd_ut, lat_deg, lon_deg, sys_char)
    return {
        "cusps": [c % 360.0 for c in cusps],
        "asc": ascmc[0] % 360.0,
        "mc": ascmc[1] % 360.0,
    }

def min_sep(a, b):
    d = abs((a - b) % 360.0)
    return d if d <= 180.0 else 360.0 - d

def build_orb_table(orb_default: float, orb_list_text: str | None):
    """Return list of orbs in ASPECTS order."""
    orbs = [orb_default] * len(ASPECTS)
    if orb_list_text:
        parts = [p.strip() for p in orb_list_text.split(",") if p.strip()]
        for i, part in enumerate(parts[:len(ASPECTS)]):
            try:
                orbs[i] = float(part)
            except ValueError:
                pass
    return orbs

def make_aspect_grid(names, longitudes, orbs):
    n = len(longitudes)
    grid = [["" for _ in range(n)] for _ in range(n)]
    for i in range(n):
        for j in range(i+1, n):
            sep = min_sep(longitudes[i], longitudes[j])
            hit = ""
            for (sym, ang), orb in zip(ASPECTS, orbs):
                if abs(sep - ang) <= orb:
                    hit = f"{sym}{sep - ang:+.2f}°"
                    break
            grid[i][j] = hit
            grid[j][i] = hit
    return {"names": names, "rows": grid, "idx": list(range(n))}

# ------------------ Routes ------------------
@app.get("/healthz")
def healthz():
    return "ok", 200

@app.route("/", methods=["GET", "POST"])
def index():
    # Defaults
    date_val = "1962-07-02"
    time_val = "23:33"
    tzid = DEFAULT_TZID
    use_fixed = DEFAULT_USE_FIXED
    fixed_offset = DEFAULT_FIXED_UTC_OFFSET
    center = DEFAULT_CENTER
    house_sys = DEFAULT_HOUSE_SYS            # 'E' or 'P'
    houses_orientation = DEFAULT_HOUSES_ORIENT  # 'ccw' or 'cw'
    zodiac_mode = DEFAULT_ZODIAC_MODE        # 'tropical' or 'sidereal_fb'
    include_nodes = DEFAULT_INCLUDE_NODES
    node_type = DEFAULT_NODE_TYPE
    orb_default = DEFAULT_ORB
    orb_list_text = DEFAULT_ORB_LIST
    lat_val = ""
    lon_val = ""

    page_error = None
    results = None
    houses = None
    aspect_grid = None
    ayan_used = ""
    tzid_display = tzid
    local_str = utc_str = jd_str = ""

    if request.method == "POST":
        # Read form
        date_val = (request.form.get("date") or date_val).strip()
        time_val = (request.form.get("time") or time_val).strip()
        tzid = (request.form.get("tzid") or tzid).strip()
        use_fixed = (request.form.get("use_fixed") == "on")
        center = (request.form.get("center") or center).strip().lower()
        house_sys = (request.form.get("house_system") or house_sys).strip().upper()
        houses_orientation = (request.form.get("houses_orientation") or houses_orientation).strip()
        zodiac_mode = (request.form.get("zodiac_mode") or zodiac_mode).strip()
        include_nodes = (request.form.get("include_nodes") == "on")
        node_type = (request.form.get("node_type") or node_type).strip().lower()
        lat_val = (request.form.get("lat") or lat_val).strip()
        lon_val = (request.form.get("lon") or lon_val).strip()
        try:
            fixed_offset = float((request.form.get("fixed_offset") or fixed_offset))
        except Exception:
            fixed_offset = DEFAULT_FIXED_UTC_OFFSET
        try:
            orb_default = float((request.form.get("orb_default") or orb_default))
        except Exception:
            orb_default = DEFAULT_ORB
        orb_list_text = (request.form.get("orb_list") or "").strip()

        try:
            # Local → UT → JD
            jd, local_dt, utc_dt, tzid_display = to_jd(date_val, time_val, tzid, use_fixed, fixed_offset)

            # Planets (+ nodes) and ayanamsa
            rows, ayan = compute_positions(
                jd_ut=jd,
                zodiac_mode=zodiac_mode,
                center=center,
                include_nodes=include_nodes,
                node_type=node_type,
            )

            # Houses if lat/lon provided
            if lat_val and lon_val:
                try:
                    lat_f = float(lat_val)
                    lon_f = float(lon_val)
                    houses = compute_houses(jd, lat_f, lon_f, system_code=house_sys)
                except Exception:
                    houses = None

            # Aspect grid: choose longitudes by selected zodiac
            names = [r["name"] for r in rows]
            if zodiac_mode == "tropical":
                longs = [float(r["trop"]) for r in rows]
            else:
                longs = [float(r["sid"]) for r in rows]
            orbs = build_orb_table(orb_default, orb_list_text)
            aspect_grid = make_aspect_grid(names, longs, orbs)

            # Final fields
            results = rows
            local_str = local_dt.strftime("%Y-%m-%d %H:%M")
            utc_str = utc_dt.strftime("%Y-%m-%d %H:%M")
            jd_str = f"{jd:.5f}"
            ayan_used = f"{ayan:.6f}"

            # Remember for /chart
            LAST_CHART["rows"] = rows
            LAST_CHART["zodiac_mode"] = zodiac_mode

        except Exception as e:
            page_error = f"{e.__class__.__name__}: {e}"

    return render_template(
        "index.html",
        # inputs/state
        date=date_val, time=time_val, tzid=tzid,
        use_fixed=use_fixed, fixed_offset=fixed_offset,
        center=center, house_system=house_sys, houses_orientation=houses_orientation,
        zodiac_mode=zodiac_mode,
        include_nodes=include_nodes, node_type=node_type,
        lat=lat_val, lon=lon_val,
        orb_default=orb_default, orb_list=orb_list_text,
        # outputs
        results=results, houses=houses, aspect_grid=aspect_grid, page_error=page_error,
        tzid_display=tzid_display, local_str=local_str, utc_str=utc_str, jd=jd_str, ayan_used=ayan_used,
    )

@app.get("/chart")
def chart():
    """Simple SVG chart wheel using last computed results (big, readable glyphs)."""
    rows = LAST_CHART.get("rows")
    zodiac_mode = LAST_CHART.get("zodiac_mode", DEFAULT_ZODIAC_MODE)
    if not rows:
        return Response("<svg xmlns='http://www.w3.org/2000/svg' width='520' height='520'></svg>",
                        mimetype="image/svg+xml")

    # choose longitudes by selected zodiac
    names = [r["name"] for r in rows]
    if zodiac_mode == "tropical":
        longs = [float(r["trop"]) for r in rows]
        title = "Chart — Tropical"
    else:
        longs = [float(r["sid"]) for r in rows]
        title = "Chart — Sidereal (F/B)"

    size = 560
    R = size // 2 - 12
    cx, cy = size // 2, size // 2

    def pol(r, ang_deg):
        # Put 0° Aries at left (9 o'clock), increase clockwise
        ang = math.radians(180 - ang_deg)
        return cx + r * math.cos(ang), cy - r * math.sin(ang)

    svg = []
    svg.append(f"<svg xmlns='http://www.w3.org/2000/svg' width='{size}' height='{size}' viewBox='0 0 {size} {size}'>")
    svg.append(f"<rect width='100%' height='100%' fill='#e6f2ff'/>")
    svg.append(f"<text x='{cx}' y='28' text-anchor='middle' font-size='18' fill='#003366'>{title}</text>")
    # outer ring
    svg.append(f"<circle cx='{cx}' cy='{cy}' r='{R}' fill='white' stroke='#003366' stroke-width='2'/>")

    # zodiac slices (12 * 30°)
    for i in range(12):
        a = i * 30.0
        x1, y1 = pol(R, a)
        svg.append(f"<line x1='{cx}' y1='{cy}' x2='{x1:.1f}' y2='{y1:.1f}' stroke='#99b3ff'/>")
        # sign label at middle of slice
        xm, ym = pol(R - 26, a + 15.0)
        glyph = SIGN_GLYPHS[i]
        svg.append(f"<text x='{xm:.1f}' y='{ym:.1f}' text-anchor='middle' dominant-baseline='middle' "
                   f"font-size='22' fill='#003366'>{glyph}</text>")

    # planet/node points
    pr = R - 60  # radius for plotting bodies
    for name, lon in zip(names, longs):
        x, y = pol(pr, lon)
        glyph = PLANET_GLYPHS.get(name, name[:1])
        svg.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='11' fill='#ffffff' stroke='#003366'/>")
        svg.append(f"<text x='{x:.1f}' y='{y+4:.1f}' text-anchor='middle' dominant-baseline='middle' "
                   f"font-size='18' fill='#003366'>{glyph}</text>")

    svg.append("</svg>")
    return Response("\n".join(svg), mimetype="image/svg+xml")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
