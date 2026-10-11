#!/usr/bin/env python3
"""
Genera calendarios .ics del fútbol argentino con API-Football:
Primera División, Primera Nacional, Primera B y Primera C.

Uso:
    API_FOOTBALL_KEY=tu_clave python3 actualizar_calendario.py
    API_FOOTBALL_KEY=tu_clave python3 actualizar_calendario.py --listar

Crea en la carpeta "docs/":
    primera.ics, primera-nacional.ics, primera-b.ics, primera-c.ics, todo.ics

No necesita instalar nada (solo Python 3.8 o más nuevo).
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://v3.football.api-sports.io"
CLAVE = os.environ.get("API_FOOTBALL_KEY", "").strip()
TEMPORADA = int(os.environ.get("TEMPORADA", datetime.now().year))
CARPETA = "docs"
DURACION = timedelta(hours=2)

# Si la detección automática por nombre falla, pegá acá el ID de la liga
# (los ves con:  python3 actualizar_calendario.py --listar).
IDS_MANUALES = {
    "primera": None,
    "primera-nacional": None,
    "primera-b": None,
    "primera-c": None,
}

# (archivo, nombre del calendario, etiqueta corta, regla para reconocer la liga por nombre)
DIVISIONES = [
    ("primera", "Primera División", "Primera",
     lambda n: "liga profesional" in n),
    ("primera-nacional", "Primera Nacional (B Nacional)", "B Nacional",
     lambda n: n in ("primera nacional", "primera b nacional")),
    ("primera-b", "Primera B", "Primera B",
     lambda n: "primera b metropolitana" in n or n == "primera b"),
    ("primera-c", "Primera C", "Primera C",
     lambda n: n == "primera c" or n.startswith("primera c ")),
]


def api(ruta, **params):
    url = f"{API}{ruta}?{urllib.parse.urlencode(params)}"
    pedido = urllib.request.Request(url, headers={"x-apisports-key": CLAVE})
    try:
        with urllib.request.urlopen(pedido, timeout=30) as r:
            datos = json.load(r)
    except urllib.error.URLError as e:
        sys.exit(f"No pude conectar con la API ({ruta}): {e}")
    if datos.get("errors"):
        sys.exit(f"La API devolvió un error en {ruta}: {datos['errors']}")
    return datos.get("response", [])


def listar_ligas():
    print(f"Ligas de Argentina, temporada {TEMPORADA}:")
    for item in api("/leagues", country="Argentina", season=TEMPORADA):
        liga = item["league"]
        print(f"  {liga['id']:>5}  {liga['type']:<6}  {liga['name']}")


def buscar_ligas():
    encontrados = {k: v for k, v in IDS_MANUALES.items() if v}
    if len(encontrados) < len(DIVISIONES):
        for item in api("/leagues", country="Argentina", season=TEMPORADA):
            liga = item["league"]
            if liga.get("type") != "League":
                continue
            nombre = liga["name"].strip().lower()
            for clave, _, _, coincide in DIVISIONES:
                if clave not in encontrados and coincide(nombre):
                    encontrados[clave] = liga["id"]
                    print(f"  {clave}: {liga['name']} (id {liga['id']})")
    return encontrados


def esc(texto):
    return (texto.replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def doblar(linea):
    """Las líneas .ics no pueden pasar de 75 bytes: se parten con CRLF + espacio."""
    datos = linea.encode("utf-8")
    salida, limite = [], 75
    while len(datos) > limite:
        corte = limite
        while (datos[corte] & 0xC0) == 0x80:  # no cortar a mitad de un carácter
            corte -= 1
        salida.append(datos[:corte].decode("utf-8"))
        datos = datos[corte:]
        limite = 74
    salida.append(datos.decode("utf-8"))
    return "\r\n ".join(salida)


def formato(dt):
    return dt.strftime("%Y%m%dT%H%M%SZ")


def evento(partido, etiqueta):
    f = partido["fixture"]
    estado = f["status"]["short"]
    if estado == "CANC":
        return None
    inicio = datetime.fromisoformat(f["date"]).astimezone(timezone.utc)
    local = partido["teams"]["home"]["name"]
    visita = partido["teams"]["away"]["name"]
    titulo = f"⚽ [{etiqueta}] {local} vs {visita}"
    if estado in ("PST", "TBD", "SUSP"):
        titulo += " (a confirmar)"
    ronda = partido["league"].get("round") or ""
    sede = f["venue"].get("name") or ""
    ciudad = f["venue"].get("city") or ""
    lugar = ", ".join(x for x in (sede, ciudad) if x)
    lineas = [
        "BEGIN:VEVENT",
        f"UID:{f['id']}@futbol-ar",
        f"DTSTAMP:{formato(inicio)}",
        f"DTSTART:{formato(inicio)}",
        f"DTEND:{formato(inicio + DURACION)}",
        f"SUMMARY:{esc(titulo)}",
        f"DESCRIPTION:{esc(etiqueta + ' - ' + ronda)}",
    ]
    if lugar:
        lineas.append(f"LOCATION:{esc(lugar)}")
    lineas.append("END:VEVENT")
    return lineas


def escribir(archivo, nombre, eventos):
    cabecera = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//futbol-ar//calendario//ES",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{esc(nombre)}",
        "X-WR-TIMEZONE:America/Argentina/Buenos_Aires",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
    ]
    lineas = cabecera + [l for ev in eventos for l in ev] + ["END:VCALENDAR"]
    ruta = os.path.join(CARPETA, archivo)
    with open(ruta, "w", encoding="utf-8", newline="") as fh:
        fh.write("\r\n".join(doblar(l) for l in lineas) + "\r\n")
    print(f"  {ruta}: {len(eventos)} partidos")


def main():
    if not CLAVE:
        sys.exit("Falta la clave: definí la variable API_FOOTBALL_KEY.")
    if "--listar" in sys.argv:
        listar_ligas()
        return
    print(f"Temporada {TEMPORADA}. Buscando ligas...")
    ids = buscar_ligas()
    if not ids:
        sys.exit("No encontré ninguna liga. Corré con --listar y completá IDS_MANUALES.")

    os.makedirs(CARPETA, exist_ok=True)
    open(os.path.join(CARPETA, ".nojekyll"), "a").close()

    todos = []
    print("Descargando partidos...")
    for clave, nombre, etiqueta, _ in DIVISIONES:
        if clave not in ids:
            print(f"  AVISO: no encontré {nombre}; se omite.")
            continue
        partidos = api("/fixtures", league=ids[clave], season=TEMPORADA)
        eventos = [e for e in (evento(p, etiqueta) for p in partidos) if e]
        if not eventos:
            print(f"  AVISO: {nombre} no devolvió partidos; no se modifica su archivo.")
            continue
        escribir(f"{clave}.ics", f"⚽ {nombre}", eventos)
        todos.extend(eventos)
    if todos:
        escribir("todo.ics", "⚽ Fútbol argentino (todas las divisiones)", todos)
    else:
        sys.exit("No se generó ningún calendario.")


if __name__ == "__main__":
    main()
