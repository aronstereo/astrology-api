import json
from engine.ephemeris import AstrologyEngine

def main():
    engine = AstrologyEngine()
    
    chart = engine.calculate_chart(
        date_str="1985-12-15",
        time_str="10:30",
        tz_str="America/Caracas",
        lat=8.6226,
        lon=-70.2075
    )

    # Imprime los caracteres en español directamente sin codificar en unicode
    print(json.dumps(chart, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()