import traceback
import sqlite3
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Optional
from google import genai
from dotenv import load_dotenv

from engine import ephemeris

# Cargar las variables de entorno desde el archivo .env
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Inicialización del cliente con el nuevo SDK de Google GenAI
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else genai.Client()

app = FastAPI(
    title="Astrology Engine API",
    description="API para el cálculo de cartas natales, sinastría e interpretaciones profundas con IA y Caché",
    version="1.6.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIGURACIÓN DE SQLITE (CACHÉ LOCAL) ---
DB_NAME = "interpretations.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS interpretations (
            aspect_signature TEXT PRIMARY KEY,
            text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

# Inicializamos la base de datos al arrancar la API
init_db()


# --- MODELOS PYDANTIC ---

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
    type: str       # Ej: 'square', 'trine', 'conjunction'
    target: str     # Ej: 'Saturn', 'Jupiter'

class InterpretationRequest(BaseModel):
    planet: str     # Ej: 'Sun'
    sign: str       # Ej: 'Virgo'
    house: int      # Ej: 10
    aspects: Optional[List[AspectItem]] = []


# --- RUTAS EXISTENTES ---

@app.get("/", response_class=HTMLResponse)
def read_root():
    index_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Astrology Engine API activa</h1><p>Archivo index.html no encontrado.</p>"

@app.post("/chart")
def calculate_chart(req: ChartRequest):
    try:
        data = ephemeris.calculate_natal_chart(
            req.year, req.month, req.day, req.hour, req.lat, req.lon
        )
        return data
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

def get_house_for_deg(abs_deg: float, houses: list) -> int:
    """Determina en qué casa astrológica cae un grado absoluto determinado."""
    for i in range(len(houses)):
        current_h = houses[i]
        next_h = houses[(i + 1) % len(houses)]
        
        c_deg = current_h["abs_deg"]
        n_deg = next_h["abs_deg"]
        
        if c_deg < n_deg:
            if c_deg <= abs_deg < n_deg:
                return current_h["house"]
        else:  # Cruce de los 0° / 360° (Aries)
            if abs_deg >= c_deg or abs_deg < n_deg:
                return current_h["house"]
    return 1

@app.post("/synastry")
def calculate_synastry(req: SynastryRequest):
    try:
        chart_a = ephemeris.calculate_natal_chart(
            req.person_a.year, req.person_a.month, req.person_a.day,
            req.person_a.hour, req.person_a.lat, req.person_a.lon
        )
        chart_b = ephemeris.calculate_natal_chart(
            req.person_b.year, req.person_b.month, req.person_b.day,
            req.person_b.hour, req.person_b.lat, req.person_b.lon
        )
        
        all_planets = chart_a["planets"] + chart_b["planets"]
        cross_aspects = ephemeris.calculate_aspects(all_planets)
        
        overlays_b_in_a = []
        if "houses" in chart_a and chart_a["houses"]:
            for p in chart_b["planets"]:
                house_num = get_house_for_deg(p["abs_deg"], chart_a["houses"])
                overlays_b_in_a.append({
                    "planet": p["name"],
                    "sign": p["sign"],
                    "house_in_a": house_num
                })

        overlays_a_in_b = []
        if "houses" in chart_b and chart_b["houses"]:
            for p in chart_a["planets"]:
                house_num = get_house_for_deg(p["abs_deg"], chart_b["houses"])
                overlays_a_in_b.append({
                    "planet": p["name"],
                    "sign": p["sign"],
                    "house_in_b": house_num
                })

        return {
            "chart_a": chart_a,
            "chart_b": chart_b,
            "cross_aspects": cross_aspects,
            "overlays_b_in_a": overlays_b_in_a,
            "overlays_a_in_b": overlays_a_in_b
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# --- ENDPOINT DE INTERPRETACIÓN PROFUNDA CON CACHÉ SQLite Y GEMINI ---

def generate_aspect_signature(planet: str, aspects: List[AspectItem]) -> str:
    """Crea una firma única basada en el planeta y sus aspectos ordenados alfabéticamente."""
    sorted_aspects = sorted([f"{a.type}-{a.target}" for a in aspects])
    signature = "_".join(sorted_aspects)
    return f"{planet}_{signature}"

@app.post("/api/v1/interpretacion-profunda")
def get_deep_interpretation(req: InterpretationRequest):
    try:
        # 1. Generar firma única
        aspect_signature = generate_aspect_signature(req.planet, req.aspects)

        # 2. Consultar en Caché (SQLite)
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT text FROM interpretations WHERE aspect_signature = ?", (aspect_signature,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                "status": "success",
                "fuente": "cache",
                "aspect_signature": aspect_signature,
                "texto": row[0]
            }

        # 3. Fallback: Llamada a Google Gemini utilizando el nuevo SDK `google-genai`
        prompt_sistema = (
            "Eres un astrólogo profesional experto en astrología psicológica y transpersonal. "
            "Genera una interpretación profunda, empática y reveladora dividida claramente en cuatro partes: "
            "Esencia, Escenario, Dinámica y Clave Evolutiva."
        )
        
        prompt_usuario = (
            f"Interpreta el planeta {req.planet} en el signo {req.sign}, "
            f"ubicado en la Casa {req.house}. Firma de aspectos clave: {aspect_signature}."
        )

        # Utilizando la clase y método moderno del SDK unificado de GenAI
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt_usuario,
            config={
                "system_instruction": prompt_sistema,
            }
        )
        texto_ia = response.text

        # 4. Guardar en SQLite para futuras consultas (Caché persistente)
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO interpretations (aspect_signature, text) VALUES (?, ?)",
            (aspect_signature, texto_ia)
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
        raise HTTPException(status_code=500, detail=str(e))