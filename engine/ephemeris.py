import swisseph as swe
from typing import Dict, List, Any

PLANETS = [
    (swe.SUN, "Sun"),
    (swe.MOON, "Moon"),
    (swe.MERCURY, "Mercury"),
    (swe.VENUS, "Venus"),
    (swe.MARS, "Mars"),
    (swe.JUPITER, "Jupiter"),
    (swe.SATURN, "Saturn"),
    (swe.URANUS, "Uranus"),
    (swe.NEPTUNE, "Neptune"),
    (swe.PLUTO, "Pluto"),
    (swe.MEAN_NODE, "Mean Node")
]

ZODIAC_SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer",
    "Leo", "Virgo", "Libra", "Scorpio",
    "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

ASPECTS = [
    {"name": "Conjunction", "angle": 0, "orb": 8, "symbol": "☌"},
    {"name": "Sextile", "angle": 60, "orb": 6, "symbol": "⚹"},
    {"name": "Square", "angle": 90, "orb": 7, "symbol": "□"},
    {"name": "Trine", "angle": 120, "orb": 8, "symbol": "△"},
    {"name": "Opposition", "angle": 180, "orb": 8, "symbol": "☍"}
]

class AstrologyEngine:
    """Clase principal para la gestión de cálculos astrológicos y efemérides."""

    @staticmethod
    def get_zodiac_position(lon: float) -> Dict[str, Any]:
        lon = float(lon) % 360
        sign_idx = int(lon // 30)
        sign_deg = lon % 30
        return {
            "sign": ZODIAC_SIGNS[sign_idx],
            "sign_deg": round(sign_deg, 2),
            "abs_deg": round(lon, 4)
        }

    @staticmethod
    def calculate_aspects(planets_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        aspects_found = []
        num_planets = len(planets_data)

        for i in range(num_planets):
            for j in range(i + 1, num_planets):
                p1 = planets_data[i]
                p2 = planets_data[j]

                diff = abs(p1["abs_deg"] - p2["abs_deg"])
                if diff > 180:
                    diff = 360 - diff

                for asp in ASPECTS:
                    target_angle = asp["angle"]
                    max_orb = asp["orb"]

                    if abs(diff - target_angle) <= max_orb:
                        exact_orb = round(abs(diff - target_angle), 2)
                        aspects_found.append({
                            "p1": p1["name"],
                            "p2": p2["name"],
                            "aspect": asp["name"],
                            "symbol": asp["symbol"],
                            "angle": target_angle,
                            "orb": exact_orb
                        })
        return aspects_found

    @classmethod
    def calculate_natal_chart(cls, year: int, month: int, day: int, hour: float, lat: float = 0.0, lon: float = 0.0) -> Dict[str, Any]:
        year = int(year)
        month = int(month)
        day = int(day)
        hour = float(hour)
        lat = float(lat)
        lon = float(lon)

        # 1. Día Juliano UT
        jd = swe.julday(year, month, day, hour)

        # 2. Planetas
        planets_result = []
        for p_id, p_name in PLANETS:
            calc_res = swe.calc_ut(jd, p_id)
            # Extracción segura de la tupla devuelta por swisseph
            res = calc_res[0] if isinstance(calc_res, (tuple, list)) and len(calc_res) > 0 else calc_res
            lon_abs = float(res[0])
            speed = float(res[3]) if len(res) > 3 else 0.0

            z_info = cls.get_zodiac_position(lon_abs)
            planets_result.append({
                "name": p_name,
                "sign": z_info["sign"],
                "sign_deg": z_info["sign_deg"],
                "abs_deg": z_info["abs_deg"],
                "is_retrograde": speed < 0
            })

        # 3. Casas y Ángulos
        try:
            houses_data = swe.houses(jd, lat, lon, b'P')
        except Exception:
            houses_data = swe.houses(jd, lat, lon, ord('P'))

        cusps = houses_data[0]
        ascmc = houses_data[1]

        houses_result = []
        for i in range(12):
            cusp_val = cusps[i]
            z_info = cls.get_zodiac_position(cusp_val)
            houses_result.append({
                "house": i + 1,
                "sign": z_info["sign"],
                "sign_deg": z_info["sign_deg"],
                "abs_deg": z_info["abs_deg"]
            })

        angles = {
            "Ascendant": cls.get_zodiac_position(ascmc[0]),
            "Midheaven": cls.get_zodiac_position(ascmc[1]),
            "Descendant": cls.get_zodiac_position((ascmc[0] + 180) % 360),
            "IC": cls.get_zodiac_position((ascmc[1] + 180) % 360)
        }

        # 4. Aspectos
        aspects_result = cls.calculate_aspects(planets_result)

        return {
            "julian_day": round(jd, 4),
            "planets": planets_result,
            "houses": houses_result,
            "angles": angles,
            "aspects": aspects_result
        }