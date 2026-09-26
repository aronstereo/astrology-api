import traceback
import sqlite3
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import List, Optional
from google import genai
from dotenv import load_dotenv

from engine import ephemeris


# ============================================================
# CONFIGURACIÓN
# ============================================================

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = (
    genai.Client(api_key=GEMINI_API_KEY)
    if GEMINI_API_KEY
    else genai.Client()
)


app = FastAPI(
    title="Astrology Engine API",
    description=(
        "API para el cálculo de cartas natales, sinastría "
        "e interpretaciones profundas con IA y Caché"
    ),
    version="1.7.0"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# SQLITE
# ============================================================

DB_NAME = "interpretations.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS interpretations (
            aspect_signature TEXT PRIMARY KEY,
            text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.commit()
    conn.close()


init_db()


# ============================================================
# MODELOS PYDANTIC
# ============================================================

class ChartRequest(BaseModel):
    year: int
    month: int
    day: int
    hour: float
    lat: Optional[float] = 0.0
    lon: Optional[float] = 0.0


class SynastryRequest(BaseModel):
    person_a: ChartRequest
    person_b: ChartRequest


class AspectItem(BaseModel):
    type: str
    target: str


class InterpretationRequest(BaseModel):
    planet: str
    sign: str
    house: int
    aspects: List[AspectItem] = Field(default_factory=list)


# ============================================================
# RUTA PRINCIPAL
# ============================================================

@app.get("/", response_class=HTMLResponse)
def read_root():
    index_path = os.path.join(
        os.path.dirname(__file__),
        "index.html"
    )

    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()

    return (
        "<h1>Astrology Engine API activa</h1>"
        "<p>Archivo index.html no encontrado.</p>"
    )


# ============================================================
# CARTA NATAL
# ============================================================

@app.post("/chart")
def calculate_chart(req: ChartRequest):
    try:
        data = ephemeris.calculate_natal_chart(
            req.year,
            req.month,
            req.day,
            req.hour,
            req.lat,
            req.lon
        )

        return data

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ============================================================
# UTILIDADES DE CASAS
# ============================================================

def get_house_for_deg(abs_deg: float, houses: list) -> int:
    """
    Determina en qué casa astrológica cae un grado absoluto.

    Gestiona correctamente el cruce entre 360° y 0°.
    """

    for i in range(len(houses)):
        current_h = houses[i]
        next_h = houses[(i + 1) % len(houses)]

        c_deg = current_h["abs_deg"]
        n_deg = next_h["abs_deg"]

        if c_deg < n_deg:
            if c_deg <= abs_deg < n_deg:
                return current_h["house"]

        else:
            # Cruce de 360° -> 0°
            if abs_deg >= c_deg or abs_deg < n_deg:
                return current_h["house"]

    return 1


# ============================================================
# SINASTRÍA
# ============================================================

def calculate_cross_aspects(
    planets_a: List[dict],
    planets_b: List[dict]
) -> List[dict]:
    """
    Calcula exclusivamente aspectos entre:

        PLANETA A ↔ PLANETA B

    No calcula:

        A ↔ A
        B ↔ B

    Esto es diferente de ephemeris.calculate_aspects(),
    que está diseñada para calcular los aspectos internos
    de una misma carta.
    """

    aspects_found = []

    # ASPECTS es utilizado internamente por ephemeris.calculate_aspects()
    # y está definido en engine/ephemeris.py.
    aspects_definition = getattr(ephemeris, "ASPECTS", [])

    if not aspects_definition:
        raise RuntimeError(
            "No se encontró la definición ASPECTS en engine.ephemeris"
        )

    for p1 in planets_a:
        for p2 in planets_b:

            diff = abs(
                float(p1["abs_deg"]) -
                float(p2["abs_deg"])
            )

            if diff > 180:
                diff = 360 - diff

            for asp in aspects_definition:

                target_angle = asp["angle"]
                max_orb = asp["orb"]

                orb_difference = abs(
                    diff - target_angle
                )

                if orb_difference <= max_orb:

                    exact_orb = round(
                        orb_difference,
                        2
                    )

                    aspects_found.append({
                        "p1": p1["name"],
                        "p2": p2["name"],
                        "aspect": asp["name"],
                        "symbol": asp["symbol"],
                        "angle": target_angle,
                        "orb": exact_orb
                    })

    # Ordenar primero por orbe más cerrado.
    aspects_found.sort(
        key=lambda x: x["orb"]
    )

    return aspects_found


# ============================================================
# SISTEMA DE COMPATIBILIDAD
# ============================================================

# Pesos base de los aspectos.
# Positivos = asociación armónica dentro del modelo.
# Negativos = asociación desafiante dentro del modelo.
#
# Esto es una heurística del producto, no una afirmación
# científica sobre relaciones humanas.

ASPECT_WEIGHTS = {
    "Conjunction": 8.0,
    "Trine": 7.0,
    "Sextile": 5.0,
    "Opposition": -4.0,
    "Square": -5.0
}


# Peso por planeta para diferentes dimensiones.

DIMENSION_PLANETS = {
    "emotional": {
        "Moon": 1.50,
        "Venus": 1.20,
        "Neptune": 0.80,
        "Sun": 0.70
    },

    "communication": {
        "Mercury": 1.60,
        "Moon": 0.70,
        "Sun": 0.60,
        "Jupiter": 0.50,
        "Saturn": 0.50
    },

    "love": {
        "Venus": 1.60,
        "Sun": 1.00,
        "Moon": 1.00,
        "Mars": 1.10,
        "Jupiter": 0.60
    },

    "sexual": {
        "Mars": 1.70,
        "Venus": 1.30,
        "Pluto": 1.40,
        "Uranus": 0.80
    },

    "stability": {
        "Saturn": 1.60,
        "Jupiter": 0.80,
        "Sun": 0.80,
        "Moon": 0.80,
        "Venus": 0.70
    }
}


def get_dimension_planet_weight(
    planet_a: str,
    planet_b: str,
    dimension: str
) -> float:

    weights = DIMENSION_PLANETS.get(
        dimension,
        {}
    )

    weight_a = weights.get(
        planet_a,
        0.35
    )

    weight_b = weights.get(
        planet_b,
        0.35
    )

    return max(
        weight_a,
        weight_b
    )


def aspect_strength(aspect: dict) -> float:
    """
    Calcula la fuerza relativa de un aspecto.

    Un orbe más cerrado tiene mayor peso.
    """

    aspect_name = aspect["aspect"]

    base_weight = ASPECT_WEIGHTS.get(
        aspect_name,
        0.0
    )

    orb = float(
        aspect.get("orb", 0)
    )

    max_orb = 10.0

    # 1.0 = aspecto exacto
    # 0.0 = aspecto fuera del rango útil
    precision = max(
        0.0,
        1.0 - (orb / max_orb)
    )

    # Evitamos que un aspecto válido desaparezca
    # completamente por su orbe.
    precision_factor = 0.35 + (
        0.65 * precision
    )

    return base_weight * precision_factor


def calculate_dimension_score(
    cross_aspects: List[dict],
    dimension: str
) -> int:

    if not cross_aspects:
        return 50

    total = 0.0
    maximum = 0.0

    for aspect in cross_aspects:

        planet_a = aspect["p1"]
        planet_b = aspect["p2"]

        planet_weight = get_dimension_planet_weight(
            planet_a,
            planet_b,
            dimension
        )

        strength = aspect_strength(
            aspect
        )

        total += strength * planet_weight

        # Máximo teórico aproximado de ese aspecto
        maximum += (
            abs(
                ASPECT_WEIGHTS.get(
                    aspect["aspect"],
                    0
                )
            )
            * planet_weight
        )

    if maximum <= 0:
        return 50

    # Convertimos el resultado a una escala 0-100.
    #
    # 0.0 = totalmente desfavorable dentro del modelo
    # 0.5 = neutral
    # 1.0 = totalmente favorable
    normalized = (
        0.5 +
        (total / maximum) * 0.5
    )

    score = round(
        normalized * 100
    )

    return max(
        0,
        min(100, score)
    )


def calculate_compatibility(
    cross_aspects: List[dict]
) -> dict:
    """
    Calcula las métricas de compatibilidad a partir
    exclusivamente de los aspectos cruzados A ↔ B.
    """

    emotional = calculate_dimension_score(
        cross_aspects,
        "emotional"
    )

    communication = calculate_dimension_score(
        cross_aspects,
        "communication"
    )

    love = calculate_dimension_score(
        cross_aspects,
        "love"
    )

    sexual = calculate_dimension_score(
        cross_aspects,
        "sexual"
    )

    stability = calculate_dimension_score(
        cross_aspects,
        "stability"
    )

    # Promedio ponderado.
    percentage = round(
        (
            emotional * 0.25 +
            communication * 0.20 +
            love * 0.25 +
            sexual * 0.15 +
            stability * 0.15
        )
    )

    return {
        "percentage": max(
            0,
            min(100, percentage)
        ),
        "emotional": emotional,
        "communication": communication,
        "love": love,
        "sexual": sexual,
        "stability": stability
    }


# ============================================================
# ANÁLISIS DE SINASTRÍA
# ============================================================

def get_top_aspects(
    cross_aspects: List[dict],
    limit: int = 8
) -> List[dict]:

    return sorted(
        cross_aspects,
        key=lambda x: x.get("orb", 99)
    )[:limit]


def generate_synastry_analysis(
    cross_aspects: List[dict],
    compatibility: dict
) -> dict:

    if not cross_aspects:
        return {
            "summary": (
                "No se encontraron aspectos cruzados "
                "dentro de los orbes configurados."
            ),
            "emotional": (
                "No hay suficientes aspectos cruzados "
                "para generar una lectura emocional."
            ),
            "communication": (
                "No hay suficientes aspectos cruzados "
                "para generar una lectura de comunicación."
            ),
            "love": (
                "No hay suficientes aspectos cruzados "
                "para generar una lectura afectiva."
            ),
            "sexual": (
                "No hay suficientes aspectos cruzados "
                "para generar una lectura de atracción."
            ),
            "long_term": (
                "No hay suficientes aspectos cruzados "
                "para evaluar la dinámica de estabilidad."
            )
        }

    harmonious = [
        a for a in cross_aspects
        if a["aspect"] in (
            "Trine",
            "Sextile"
        )
    ]

    challenging = [
        a for a in cross_aspects
        if a["aspect"] in (
            "Square",
            "Opposition"
        )
    ]

    conjunctions = [
        a for a in cross_aspects
        if a["aspect"] == "Conjunction"
    ]

    top = get_top_aspects(
        cross_aspects,
        limit=6
    )

    aspect_descriptions = []

    for aspect in top:
        aspect_descriptions.append(
            f'{aspect["p1"]} {aspect["symbol"]} '
            f'{aspect["p2"]} '
            f'(orbe {aspect["orb"]}°)'
        )

    top_text = ", ".join(
        aspect_descriptions
    )

    harmony_text = (
        f"Se identificaron {len(harmonious)} "
        "aspectos armónicos principales."
        if harmonious
        else
        "No se identificaron aspectos armónicos "
        "principales dentro de los orbes configurados."
    )

    challenge_text = (
        f"Se identificaron {len(challenging)} "
        "aspectos de tensión."
        if challenging
        else
        "No se identificaron aspectos de tensión "
        "principales dentro de los orbes configurados."
    )

    conjunction_text = (
        f"También aparecen {len(conjunctions)} "
        "conjunciones, cuya interpretación depende "
        "de los planetas involucrados."
        if conjunctions
        else
        "No se identificaron conjunciones "
        "entre los planetas considerados."
    )

    return {
        "summary": (
            f"La sinastría contiene {len(cross_aspects)} "
            "aspectos cruzados entre ambas cartas. "
            f"{harmony_text} {challenge_text} "
            f"{conjunction_text} "
            f"Los aspectos más cerrados son: {top_text}."
        ),

        "emotional": (
            f"La dimensión emocional obtiene "
            f"{compatibility['emotional']}/100. "
            "La lectura se basa principalmente en "
            "las conexiones cruzadas que involucran "
            "la Luna, Venus y otros factores "
            "emocionales del modelo."
        ),

        "communication": (
            f"La dimensión de comunicación obtiene "
            f"{compatibility['communication']}/100. "
            "Mercurio y sus aspectos cruzados tienen "
            "un peso destacado en esta dimensión."
        ),

        "love": (
            f"La dimensión afectiva obtiene "
            f"{compatibility['love']}/100. "
            "Venus, Marte, Sol y Luna reciben "
            "mayor peso en esta parte del modelo."
        ),

        "sexual": (
            f"La dimensión de atracción obtiene "
            f"{compatibility['sexual']}/100. "
            "Marte, Venus, Plutón y Urano reciben "
            "mayor peso en esta dimensión."
        ),

        "long_term": (
            f"La dimensión de estabilidad obtiene "
            f"{compatibility['stability']}/100. "
            "Saturno y los aspectos asociados "
            "tienen un peso destacado en esta métrica."
        )
    }


# ============================================================
# ENDPOINT DE SINASTRÍA
# ============================================================

@app.post("/synastry")
def calculate_synastry(req: SynastryRequest):

    try:

        # --------------------------------------------------------
        # 1. CALCULAR CARTA A
        # --------------------------------------------------------

        chart_a = ephemeris.calculate_natal_chart(
            req.person_a.year,
            req.person_a.month,
            req.person_a.day,
            req.person_a.hour,
            req.person_a.lat,
            req.person_a.lon
        )


        # --------------------------------------------------------
        # 2. CALCULAR CARTA B
        # --------------------------------------------------------

        chart_b = ephemeris.calculate_natal_chart(
            req.person_b.year,
            req.person_b.month,
            req.person_b.day,
            req.person_b.hour,
            req.person_b.lat,
            req.person_b.lon
        )


        planets_a = chart_a.get(
            "planets",
            []
        )

        planets_b = chart_b.get(
            "planets",
            []
        )


        # --------------------------------------------------------
        # 3. ASPECTOS CRUZADOS REALES A ↔ B
        # --------------------------------------------------------

        cross_aspects = calculate_cross_aspects(
            planets_a,
            planets_b
        )


        # --------------------------------------------------------
        # 4. OVERLAYS B → A
        # --------------------------------------------------------

        overlays_b_in_a = []

        if chart_a.get("houses"):

            for planet in planets_b:

                house_num = get_house_for_deg(
                    planet["abs_deg"],
                    chart_a["houses"]
                )

                overlays_b_in_a.append({
                    "planet": planet["name"],
                    "sign": planet["sign"],
                    "house_in_a": house_num
                })


        # --------------------------------------------------------
        # 5. OVERLAYS A → B
        # --------------------------------------------------------

        overlays_a_in_b = []

        if chart_b.get("houses"):

            for planet in planets_a:

                house_num = get_house_for_deg(
                    planet["abs_deg"],
                    chart_b["houses"]
                )

                overlays_a_in_b.append({
                    "planet": planet["name"],
                    "sign": planet["sign"],
                    "house_in_b": house_num
                })


        # --------------------------------------------------------
        # 6. COMPATIBILIDAD
        # --------------------------------------------------------

        compatibility = calculate_compatibility(
            cross_aspects
        )


        # --------------------------------------------------------
        # 7. ANÁLISIS
        # --------------------------------------------------------

        analysis = generate_synastry_analysis(
            cross_aspects,
            compatibility
        )


        # --------------------------------------------------------
        # 8. RESPUESTA
        # --------------------------------------------------------

        return {

            "chart_a": chart_a,

            "chart_b": chart_b,

            "cross_aspects": cross_aspects,

            "overlays_b_in_a": overlays_b_in_a,

            "overlays_a_in_b": overlays_a_in_b,

            "compatibility": compatibility,

            # Alias explícito para compatibilidad
            # con diferentes versiones del frontend.
            "compatibility_percentage": (
                compatibility["percentage"]
            ),

            "analysis": analysis,

            "synastry_summary": {
                "total_cross_aspects": len(
                    cross_aspects
                ),
                "harmonious_aspects": len([
                    a for a in cross_aspects
                    if a["aspect"] in (
                        "Trine",
                        "Sextile"
                    )
                ]),
                "challenging_aspects": len([
                    a for a in cross_aspects
                    if a["aspect"] in (
                        "Square",
                        "Opposition"
                    )
                ]),
                "conjunctions": len([
                    a for a in cross_aspects
                    if a["aspect"] == "Conjunction"
                ])
            }
        }


    except Exception as e:

        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ============================================================
# INTERPRETACIÓN PROFUNDA
# ============================================================

def generate_aspect_signature(
    planet: str,
    aspects: List[AspectItem]
) -> str:

    sorted_aspects = sorted(
        [
            f"{a.type}-{a.target}"
            for a in aspects
        ]
    )

    signature = "_".join(
        sorted_aspects
    )

    return f"{planet}_{signature}"


@app.post("/api/v1/interpretacion-profunda")
def get_deep_interpretation(
    req: InterpretationRequest
):

    try:

        # --------------------------------------------------------
        # 1. GENERAR FIRMA
        # --------------------------------------------------------

        aspect_signature = generate_aspect_signature(
            req.planet,
            req.aspects
        )


        # --------------------------------------------------------
        # 2. BUSCAR EN CACHE
        # --------------------------------------------------------

        conn = sqlite3.connect(
            DB_NAME
        )

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT text
            FROM interpretations
            WHERE aspect_signature = ?
            """,
            (aspect_signature,)
        )

        row = cursor.fetchone()

        conn.close()


        if row:

            return {
                "status": "success",
                "fuente": "cache",
                "aspect_signature": aspect_signature,
                "texto": row[0]
            }


        # --------------------------------------------------------
        # 3. GEMINI
        # --------------------------------------------------------

        prompt_sistema = (
            "Eres un astrólogo profesional experto "
            "en astrología psicológica y transpersonal. "
            "Genera una interpretación profunda, "
            "empática y reveladora dividida claramente "
            "en cuatro partes: Esencia, Escenario, "
            "Dinámica y Clave Evolutiva."
        )


        prompt_usuario = (
            f"Interpreta el planeta {req.planet} "
            f"en el signo {req.sign}, "
            f"ubicado en la Casa {req.house}. "
            f"Firma de aspectos clave: "
            f"{aspect_signature}."
        )


        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt_usuario,
            config={
                "system_instruction": prompt_sistema,
            }
        )


        texto_ia = response.text


        # --------------------------------------------------------
        # 4. GUARDAR CACHE
        # --------------------------------------------------------

        conn = sqlite3.connect(
            DB_NAME
        )

        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR REPLACE INTO interpretations
            (aspect_signature, text)
            VALUES (?, ?)
            """,
            (
                aspect_signature,
                texto_ia
            )
        )

        conn.commit()
        conn.close()


        return {
            "status": "success",
            "fuente": "ia",
            "aspect_signature": aspect_signature,
            "texto": texto_ia
        }


    except Exception as e:

        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
