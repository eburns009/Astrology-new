import os
import requests
import swisseph as swe
from flask import Flask, request, render_template

app = Flask(__name__)

# GeoNames credentials
GEONAMES_USERNAME = os.getenv("GEONAMES_USERNAME", "newastologyemerging")

@app.route("/", methods=["GET", "POST"])
def index():
    error = None
    rows = []

    if request.method == "POST":
        city = request.form.get("city")
        date_str = request.form.get("date")
        time_str = request.form.get("time")
        tz = request.form.get("timezone")
        offset = float(request.form.get("offset") or 0)

        # --- GeoNames lookup ---
        lat, lon, place_name = None, None, None
        try:
            resp = requests.get(
                "http://api.geonames.org/searchJSON",
                params={
                    "q": city,
                    "maxRows": 1,
                    "username": GEONAMES_USERNAME,
                    "featureClass": "P",
                    "orderby": "relevance"
                }
            )
            data = resp.json()
            if data.get("geonames"):
                g = data["geonames"][0]
                lat = float(g["lat"])
                lon = float(g["lng"])
                place_name = g["name"]
            else:
                error = "No matching location found."
        except Exception as e:
            error = f"GeoNames error: {e}"

        # --- Planetary positions ---
        if lat is not None and lon is not None:
            # parse date + time
            year, month, day = map(int, date_str.split("-"))
            hour, minute = map(int, time_str.split(":"))
            ut = hour + minute/60.0

            jd = swe.julday(year, month, day, ut)

            # Tropical mode (default)
            swe.set_sid_mode(swe.SIDM_NONE, 0, 0)

            planets = [
                (swe.SUN, "Sun"), (swe.MOON, "Moon"), (swe.MERCURY, "Mercury"),
                (swe.VENUS, "Venus"), (swe.MARS, "Mars"), (swe.JUPITER, "Jupiter"),
                (swe.SATURN, "Saturn"), (swe.URANUS, "Uranus"),
                (swe.NEPTUNE, "Neptune"), (swe.PLUTO, "Pluto")
            ]

            # --- Tropical first ---
            tropical_positions = {}
            for code, name in planets:
                lon_trop, lat_trop, dist = swe.calc_ut(jd, code)[0]
                tropical_positions[name] = lon_trop

            # --- Sidereal Fagan/Bradley ---
            swe.set_sid_mode(swe.SIDM_FAGAN_BRADLEY, offset, 0)
            sidereal_positions = {}
            for code, name in planets:
                lon_sid, lat_sid, dist = swe.calc_ut(jd, code)[0]
                sidereal_positions[name] = lon_sid

            # --- Merge rows for table ---
            for name in tropical_positions.keys():
                rows.append({
                    "name": name,
                    "tropical": f"{tropical_positions[name]:.6f}",
                    "sidereal": f"{sidereal_positions[name]:.6f}"
                })

    return render_template("chart.html", error=error, rows=rows)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
