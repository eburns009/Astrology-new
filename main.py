from __future__ import annotations
from flask import Flask, request, render_template, make_response
from zoneinfo import ZoneInfo
import datetime as dt
import os
import io
import csv
import traceback
import requests
import swisseph as swe

app = Flask(__name__)
app.config["PROPAGATE_EXCEPTIONS"] = True

# ------------------ Config ------------------
DEFAULT_TZID = "America/New_York"
DEFAULT_USE_FIXED = True           # For mid-20th century U.S. births, this can match "no DST" workflows
DEFAULT_FIXED_UTC_OFFSET = -5.0    # Hours (EST)
DEFAULT_FB_EXTRA_OFFSET_DEG = 0.0  # Pure Fagan/Bradley by default
DEFAULT_CENTER = "geo"             # 'geo' or 'helio'
DEFAULT_HOUSE_SYS = "EQUAL"        # 'EQUAL' or 'PLACIDUS'

GEONAMES_USERNAME = os.getenv("GEONAMES_USERNAME", "newastologyemerging")
GEONAMES_BASE = "http://api.geonames.org"  # free tier uses HTTP

PLANETS = [
    ("Sun", swe.SUN), ("Moon", swe.MOON), ("Mercury", swe.MERCURY),
    ("Venus", swe.VENUS), ("Mars", swe.MARS), ("Jupiter", swe.JUPITER),
    ("Saturn", swe.SATURN), ("Uranus", swe.URANUS), ("Neptune", swe.NEPTUNE),
    ("Pluto", swe.PLUTO),
]

# ------------------ Helpers ------------------

def fmt_zodiac(deg: float) -> str:
    """Return D°M'S\" Sign from 0–360 longitude."""
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
    """Parse local date/time and return (jd_ut, local_dt, utc_dt, tzid_display)."""
    local_dt = dt.datetime.strptime(f"{local_date} {local_time}", "%Y-%m-%d %H:%M")
    if use_fixed:
        tzinfo = dt.timezone(dt.timedelta(hours=float(fixed_offset_h)))
        tzid_display = f"UTC{float(fixed_offset_h):+.0f} (fixed)"
    else:
        tzinfo = ZoneInfo(tzid)
        tzid_display = tzid
    local_dt = local_dt.replace(tzinfo=tzinfo)
    utc_dt = local_dt.astimezone(dt.timezone.utc)
    h = utc_dt.hour + utc_dt.minute/60 + utc_dt.second/3600
    jd = swe.julday(utc_dt.year, utc_dt.month, utc_dt.day, h)
    return jd, local_dt, utc_dt, tzid_display

def compute_positions(jd_ut: float, fb_extra_offset: float, center: str = "geo"):
    """Return rows (tropical + Fagan/Bradley sidereal) and ayanamsa used."""
    flags = 0
    if center == "helio":
        flags |= swe.FLG_HELCTR

    # Tropical (sidereal mode doesn't affect calc_ut longitudes)
    trop = {}
    for name, code in PLANETS:
        vals, _flag = swe.calc_ut(jd_ut, code, flags)
        lon = float(vals[0]) % 360.0
        trop[name] = lon

    # Ayanamsa (Fagan/Bradley + optional extra)
    swe.set_sid_mode(swe.SIDM_FAGAN_BRADLEY)
    ayan = swe.get_ayanamsa_ut(jd_ut) + float(fb_extra_offset)

    rows = []
    for name, _ in PLANETS:
        lon_t = trop[name]
        lon_s = (lon_t - ayan) % 360.0
        rows.append({
            "name": name,
            "trop": f"{lon_t:.6f}",
            "trop_sign": fmt_zodiac(lon_t),
            "sid": f"{lon_s:.6f}",
            "sid_sign": fmt_zodiac(lon_s),
        })
    return rows, ayan

def compute_houses(jd_ut: float, lat_deg: float, lon_deg: float, system: str = "EQUAL"):
    """Compute houses & angles. system: 'EQUAL' or 'PLACIDUS'. Returns dict with cusps, asc, mc."""
    sys_char = b'E' if system.upper() == "EQUAL" else b'P'
    cusps, ascmc = swe.houses_ex(jd_ut, lat_deg, lon_deg, sys_char)
    return {
        "cusps": [c % 360.0 for c in cusps],
        "asc": ascmc[0] % 360.0,
        "mc": ascmc[1] % 360.0,
    }

# ---- GeoNames helpers ----

def geonames_search(q: str, max_rows: int = 8):
    try:
        r = requests.get(
            f"{GEONAMES_BASE}/searchJSON",
            params={"q": q, "maxRows": max_rows, "username": GEONAMES_USERNAME, "featureClass": "P", "orderby": "relevance"},
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        if "status" in data:
            msg = data["status"].get("message", "GeoNames error")
            code = data["status"].get("value", "")
            return [dict(_ok=False, label=f"GeoNames error: {msg} (status {code})")]
        out = []
        for g in data.get("geonames", []):
            out.append(dict(
                _ok=True,
                name=g.get("name", ""),
                admin=g.get("adminName1", ""),
                country=g.get("countryName", ""),
                lat=g.get("lat", ""),
                lng=g.get("lng", ""),
            ))
        return out
    except Exception as e:
        return [dict(_ok=False, label=f"GeoNames error: {e}")]

def geonames_timezone(lat: float, lng: float) -> str:
    r = requests.get(f"{GEONAMES_BASE}/timezoneJSON", params={"lat": lat, "lng": lng, "username": GEONAMES_USERNAME}, timeout=12)
    r.raise_for_status()
    data = r.json()
    if "status" in data:
        raise RuntimeError(data["status"].get("message", "GeoNames error"))
    return data.get("timezoneId") or DEFAULT_TZID

# ------------------ Routes ------------------

@app.after_request
def add_headers(resp):
    # Small, safe security hardening
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp

@app.get("/healthz")
def healthz():
    return "ok", 200

@app.route("/", methods=["GET", "POST"])
def index():
    # Defaults shown on first load
    date_val = "1962-07-02"
    time_val = "23:33"
    tzid = DEFAULT_TZID
    use_fixed = DEFAULT_USE_FIXED
    fixed_offset = DEFAULT_FIXED_UTC_OFFSET
    fb_extra = DEFAULT_FB_EXTRA_OFFSET_DEG
    center = DEFAULT_CENTER
    house_sys = DEFAULT_HOUSE_SYS
    lat_val = ""  # optional for houses
    lon_val = ""

    page_error = None
    results = None
    tzid_display = tzid
    local_str = utc_str = jd_str = ayan_used = ""
    houses = None
    city_results = None
    selected_city = None

    # City search via GET ?city=...
    if request.method == "GET":
        q = (request.args.get("city") or "").strip()
        if q:
            city_results = geonames_search(q)

    if request.method == "POST":
        # Read form with gentle defaults
        date_val = (request.form.get("date") or date_val).strip()
        time_val = (request.form.get("time") or time_val).strip()
        tzid = (request.form.get("tzid") or tzid).strip()
        use_fixed = (request.form.get("use_fixed") == "on")
        center = (request.form.get("center") or center).strip().lower()
        house_sys = (request.form.get("house_system") or house_sys).strip().upper()
        lat_val = (request.form.get("lat") or lat_val).strip()
        lon_val = (request.form.get("lon") or lon_val).strip()
        selected_city = request.form.get("selected_city")
        try:
            fixed_offset = float((request.form.get("fixed_offset") or fixed_offset))
        except Exception:
            fixed_offset = DEFAULT_FIXED_UTC_OFFSET
        try:
            fb_extra = float((request.form.get("fb_offset") or fb_extra))
        except Exception:
            fb_extra = DEFAULT_FB_EXTRA_OFFSET_DEG

        try:
            # Local → UT → JD
            jd, local_dt, utc_dt, tzid_display = to_jd(date_val, time_val, tzid, use_fixed, fixed_offset)

            # Compute planets
            rows, ayan = compute_positions(jd, fb_extra, center=center)

            # Optional: houses if lat/lon provided
            if lat_val and lon_val:
                try:
                    lat_f = float(lat_val)
                    lon_f = float(lon_val)
                    houses = compute_houses(jd, lat_f, lon_f, system=house_sys)
                except Exception:
                    houses = None

            results = rows
            local_str = local_dt.strftime("%Y-%m-%d %H:%M")
            utc_str = utc_dt.strftime("%Y-%m-%d %H:%M")
            jd_str = f"{jd:.5f}"
            ayan_used = f"{ayan:.6f}"
        except Exception as e:
            traceback.print_exc()
            page_error = f"{e.__class__.__name__}: {e}"

    return render_template(
        "index.html",
        date=date_val, time=time_val, tzid=tzid,
        use_fixed=use_fixed, fixed_offset=fixed_offset, fb_offset=fb_extra,
        center=center, house_system=house_sys, lat=lat_val, lon=lon_val,
        results=results, houses=houses, page_error=page_error,
        tzid_display=tzid_display, local_str=local_str, utc_str=utc_str,
        jd=jd_str, ayan_used=ayan_used,
        city_results=city_results, selected_city=selected_city,
        app_version="main.py (final)"
    )

@app.post("/select_city")
def select_city():
    """Accept a GeoNames selection and prefill lat/lon and tzid into the form."""
    try:
        name = request.form.get("name", "")
        admin = request.form.get("admin", "")
        country = request.form.get("country", "")
        lat_raw = (request.form.get("lat") or "").strip()
        lng_raw = (request.form.get("lng") or "").strip()
        if not lat_raw or not lng_raw:
            raise ValueError("Missing coordinates from selection")
        lat = float(lat_raw); lng = float(lng_raw)
        try:
            tzid = geonames_timezone(lat, lng)
        except Exception:
            tzid = DEFAULT_TZID
        label = ", ".join([v for v in (name, admin, country) if v])
        # Render index with prefilled fields
        return render_template(
            "index.html",
            date="1962-07-02", time="23:33", tzid=tzid,
            use_fixed=DEFAULT_USE_FIXED, fixed_offset=DEFAULT_FIXED_UTC_OFFSET, fb_offset=DEFAULT_FB_EXTRA_OFFSET_DEG,
            center=DEFAULT_CENTER, house_system=DEFAULT_HOUSE_SYS,
            lat=f"{lat}", lon=f"{lng}",
            results=None, houses=None, page_error=None,
            tzid_display=tzid, local_str="", utc_str="", jd="", ayan_used="",
            city_results=None, selected_city=label, app_version="main.py (final)"
        )
    except Exception as e:
        traceback.print_exc()
        return render_template(
            "index.html",
            date="1962-07-02", time="23:33", tzid=DEFAULT_TZID,
            use_fixed=DEFAULT_USE_FIXED, fixed_offset=DEFAULT_FIXED_UTC_OFFSET, fb_offset=DEFAULT_FB_EXTRA_OFFSET_DEG,
            center=DEFAULT_CENTER, house_system=DEFAULT_HOUSE_SYS,
            lat="", lon="",
            results=None, houses=None, page_error=f"Selection error: {e}",
            tzid_display=DEFAULT_TZID, local_str="", utc_str="", jd="", ayan_used="",
            city_results=None, selected_city=None, app_version="main.py (final)"
        )

# -------- Ephemeris (CSV, BCE supported) --------

def parse_iso_date(date_str: str):
    """Parse YYYY-MM-DD or -YYYY-MM-DD (astronomical year numbering). Returns (y,m,d)."""
    sign = 1
    s = date_str.strip()
    if s.startswith("-"):
        sign = -1
        s = s[1:]
    y, m, d = s.split("-")
    return sign * int(y), int(m), int(d)

@app.post("/ephemeris")
def ephemeris():
    try:
        start_str = (request.form.get("eph_start") or "1962-07-01").strip()
        end_str   = (request.form.get("eph_end")   or "1962-07-03").strip()
        step_str  = (request.form.get("eph_step")  or "1 day").strip().lower()
        center    = (request.form.get("eph_center") or "geo").strip().lower()
        fb_extra  = float((request.form.get("fb_offset") or DEFAULT_FB_EXTRA_OFFSET_DEG))

        step_hours = 24
        if step_str.startswith("6"):
            step_hours = 6
        elif step_str.startswith("1 hour") or step_str in ("1h", "1 hour"):
            step_hours = 1

        y1,m1,d1 = parse_iso_date(start_str)
        y2,m2,d2 = parse_iso_date(end_str)
        jd1 = swe.julday(y1, m1, d1, 0.0)
        jd2 = swe.julday(y2, m2, d2, 0.0)
        if jd2 < jd1:
            jd1, jd2 = jd2, jd1

        output = io.StringIO()
        writer = csv.writer(output)
        header = ["ISO_UT", "AYAN_FB_PLUS", "CENTER"] + [name for name, _ in PLANETS]
        writer.writerow(header)

        jd = jd1
        step_days = step_hours / 24.0
        while jd <= jd2 + 1e-9:
            swe.set_sid_mode(swe.SIDM_FAGAN_BRADLEY)
            ayan = swe.get_ayanamsa_ut(jd) + fb_extra

            y, m, d, f = swe.revjul(jd)
            hh = int(f)
            mm = int((f - hh) * 60)
            iso = f"{y:04d}-{m:02d}-{d:02d}T{hh:02d}:{mm:02d}:00Z"

            flags = 0
            if center == "helio":
                flags |= swe.FLG_HELCTR

            row = [iso, f"{ayan:.6f}", center]
            for name, code in PLANETS:
                vals, _flag = swe.calc_ut(jd, code, flags)
                lon_trop = float(vals[0]) % 360.0
                lon_sid = (lon_trop - ayan) % 360.0
                row.append(f"{lon_sid:.6f}")
            writer.writerow(row)
            jd += step_days

        csv_bytes = output.getvalue().encode("utf-8")
        resp = make_response(csv_bytes)
        resp.headers["Content-Type"] = "text/csv; charset=utf-8"
        resp.headers["Content-Disposition"] = "attachment; filename=ephemeris_fagan_allen.csv"
        return resp

    except Exception as e:
        traceback.print_exc()
        return f"Error generating ephemeris: {e}", 400

# -------- Ephemeris preview (printable HTML) --------
@app.post("/ephemeris/preview")
def ephemeris_preview():
    try:
        start_str = (request.form.get("eph_start") or "1962-07-01").strip()
        end_str   = (request.form.get("eph_end")   or "1962-07-03").strip()
        step_str  = (request.form.get("eph_step")  or "1 day").strip().lower()
        center    = (request.form.get("eph_center") or "geo").strip().lower()
        fb_extra  = float((request.form.get("fb_offset") or DEFAULT_FB_EXTRA_OFFSET_DEG))

        step_hours = 24
        if step_str.startswith("6"):
            step_hours = 6
        elif step_str.startswith("1 hour") or step_str in ("1h", "1 hour"):
            step_hours = 1

        y1,m1,d1 = parse_iso_date(start_str)
        y2,m2,d2 = parse_iso_date(end_str)
        jd1 = swe.julday(y1, m1, d1, 0.0)
        jd2 = swe.julday(y2, m2, d2, 0.0)
        if jd2 < jd1:
            jd1, jd2 = jd2, jd1

        rows = []
        jd = jd1
        step_days = step_hours / 24.0
        # Guardrail to avoid long server render times:
        row_limit = 5000
        count = 0
        while jd <= jd2 + 1e-9 and count < row_limit:
            swe.set_sid_mode(swe.SIDM_FAGAN_BRADLEY)
            ayan = swe.get_ayanamsa_ut(jd) + fb_extra
            y, m, d, f = swe.revjul(jd)
            hh = int(f); mm = int((f - hh) * 60)
            iso = f"{y:04d}-{m:02d}-{d:02d} {hh:02d}:{mm:02d} UT"

            flags = 0
            if center == "helio":
                flags |= swe.FLG_HELCTR

            row = {"iso": iso, "ayan": f"{ayan:.6f}", "center": center}
            for name, code in PLANETS:
                vals, _flag = swe.calc_ut(jd, code, flags)
                lon_trop = float(vals[0]) % 360.0
                lon_sid = (lon_trop - ayan) % 360.0
                row[name] = f"{lon_sid:.6f}"
            rows.append(row)
            jd += step_days
            count += 1

        truncated = (count >= row_limit)
        return render_template("ephemeris.html", rows=rows, center=center, truncated=truncated, app_version="main.py (final)")
    except Exception as e:
        traceback.print_exc()
        return f"Error generating preview: {e}", 400

if __name__ == "__main__":
    # Local dev run (Render uses gunicorn via render.yaml/startCommand)
    app.run(host="0.0.0.0", port=8000)
