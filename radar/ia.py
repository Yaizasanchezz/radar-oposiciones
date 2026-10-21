"""Lectura de convocatorias con Claude (API de Anthropic) y modo básico sin IA.

Se pide a Claude que devuelva un JSON con un esquema fijo (structured outputs),
así que la respuesta siempre se puede guardar y mostrar sin adivinar formatos.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re

import requests

from .config import Config
from .fuentes import Anuncio

log = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"


def _n(tipo: str) -> dict:
    """Tipo que admite null."""
    return {"anyOf": [{"type": tipo}, {"type": "null"}]}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}


ESQUEMA = _obj({
    "tipo_publicacion": {"type": "string", "enum": [
        "convocatoria", "bases", "extracto", "oferta_empleo_publico", "otro"]},
    "resumen": {"type": "string", "description": "1-2 frases en español para una persona opositora"},
    "plazo": _obj({
        "dias": _n("integer"),
        "tipo": {"type": "string", "enum": ["habiles", "naturales", "meses", "desconocido"]},
        "cuenta_desde": {"type": "string", "enum": [
            "esta_publicacion", "extracto_boe", "otra_publicacion", "no_aplica", "desconocido"],
            "description": "esta_publicacion si el plazo empieza al día siguiente de ESTE anuncio; "
                           "extracto_boe si empezará cuando salga el extracto en el BOE"},
        "fecha_fin_explicita": _n("string"),
    }),
    "referencia_bases": _n("string"),
    "bases_bocm": _obj({
        "numero": _n("integer"),
        "fecha": _n("string"),
    }),
    "apertura_estimada": _n("string"),
    "procesos": {"type": "array", "items": _obj({
        "puesto": {"type": "string", "description": "Denominación corta: p. ej. 'Auxiliar Administrativo'"},
        "cuerpo_escala": {"type": "string"},
        "subgrupo": {"type": "string", "enum": [
            "A1", "A2", "B", "C1", "C2", "AP", "LABORAL", "DESCONOCIDO"]},
        "grupo_laboral_equivalente": _n("string"),
        "personal": {"type": "string", "enum": [
            "funcionario", "laboral", "interino", "bolsa", "desconocido"]},
        "turno_libre": {"type": "boolean"},
        "plazas_libre": _n("integer"),
        "plazas_total": _n("integer"),
        "sistema": {"type": "string", "enum": [
            "oposicion", "concurso-oposicion", "concurso", "desconocido"]},
        "titulacion_requerida": {"type": "string"},
        "requisitos_extra": {"type": "string"},
        "accesible": {"type": "string", "enum": ["si", "no", "dudoso"]},
        "motivo_accesible": {"type": "string"},
        "url_inscripcion": _n("string"),
        "tasa_euros": _n("number"),
        "temario": _obj({
            "disponible": {"type": "boolean"},
            "num_temas": _n("integer"),
            "bloques": {"type": "array", "items": _obj({
                "nombre": {"type": "string"},
                "num_temas": _n("integer"),
                "resumen": {"type": "string"},
            })},
        }),
        "ejercicios": {"type": "array", "items": _obj({
            "nombre": {"type": "string"},
            "descripcion": {"type": "string"},
        })},
        "dificultad": _obj({
            "nivel": {"type": "integer", "description": "1 (muy asequible) a 5 (muy difícil)"},
            "explicacion": {"type": "string"},
        }),
        "aspirantes": _obj({
            "estimacion": {"type": "string", "description": "Rango, p. ej. '3.000–5.000 (≈ 60 por plaza)'"},
            "explicacion": {"type": "string"},
        }),
    })},
})

INSTRUCCIONES = """Eres un asistente experto en oposiciones en España. Lees anuncios oficiales \
(BOE, BOCM) y extraes datos para una opositora con este perfil:
- Titulación: {titulacion}. Títulos concretos: {titulos}.
- Puede acceder a los subgrupos: {subgrupos} (y categorías laborales equivalentes, p. ej. \
grupos III, IV y V o E1-E3 del personal laboral; NO a A1, A2 ni B).

Reglas:
1. Crea un elemento en "procesos" por cada cuerpo/escala/categoría distinta del anuncio (un \
ayuntamiento puede convocar varias plazas a la vez). Si es una Oferta de Empleo Público, \
incluye SOLO los cuerpos/categorías de C1, C2, AP o equivalentes laborales.
2. "accesible": "si" si el subgrupo es accesible, hay turno libre y la titulación exigida \
puede ser Bachiller, Técnico, Técnico Superior, ESO o ninguna. "no" si es A1/A2/B, solo \
promoción interna o exige un título universitario. "dudoso" si exige un título concreto de \
FP que no coincide con los suyos u otro requisito poco claro. Explica el motivo en una frase.
3. Plazo: "cuenta_desde" = "esta_publicacion" cuando el plazo de solicitudes empieza al día \
siguiente de publicarse ESTE anuncio (convocatorias del Estado en el BOE, de la Comunidad en \
el BOCM, extractos de ayuntamientos en el BOE). "extracto_boe" cuando el anuncio son bases \
que dicen que el plazo empezará tras publicarse el extracto en el BOE. Si el texto da una \
fecha de fin concreta, ponla en formato AAAA-MM-DD.
4. Temario: si el anuncio incluye el programa, cuenta los temas, agrúpalos en bloques (los \
del propio anuncio o, si no tiene, por materias) y resume cada bloque en una frase con \
ejemplos de contenido. Si no viene (p. ej. extractos que remiten a otras bases), \
"disponible": false.
5. Ejercicios: cada prueba con su formato (nº de preguntas, tiempo, si es eliminatoria, \
pruebas físicas, idiomas...). Si no viene, lista vacía.
6. Dificultad 1-5 teniendo en cuenta nº de temas, tipo de ejercicios, plazas y competencia \
habitual. Aspirantes: estimación orientativa en rango; si conoces ediciones anteriores de \
esta oposición, básate en ellas; si no, usa ratios típicos (las de Estado C2 y Policía \
suelen superar 50-100 aspirantes por plaza; plazas sueltas de ayuntamientos pequeños, \
menos). Deja claro que es una estimación.
7. "apertura_estimada": solo si el plazo aún no está abierto (OEP o bases a la espera del \
extracto): cuándo se espera que se abra y por qué (p. ej. "las OEP del Estado suelen \
convocarse en 6-12 meses").
8. "url_inscripcion": el enlace exacto para presentar la solicitud si aparece en el texto.
   "bases_bocm": si el anuncio dice que las bases se publicaron en el Boletín Oficial de la \
Comunidad de Madrid, su número y fecha (AAAA-MM-DD); si no, null en ambos.
9. Escribe todo en español claro y breve. No inventes datos que no estén en el texto salvo \
la dificultad, los aspirantes y la apertura estimada, que son estimaciones."""


def _recortar(texto: str, maximo: int) -> str:
    """Si es muy largo, conserva el principio (bases) y el final (anexos con el temario)."""
    if len(texto) <= maximo:
        return texto
    cabeza = int(maximo * 0.55)
    cola = maximo - cabeza
    return texto[:cabeza] + "\n\n[... texto recortado ...]\n\n" + texto[-cola:]


def analizar_con_claude(anuncio: Anuncio, texto: str, cfg: Config) -> dict:
    sistema = INSTRUCCIONES.format(
        titulacion=cfg.titulacion,
        titulos=", ".join(cfg.mis_titulos) or "no indicados",
        subgrupos=", ".join(cfg.subgrupos),
    )
    usuario = (
        f"Fecha de hoy: {dt.date.today():%Y-%m-%d}\n"
        f"Boletín: {anuncio.fuente} del {anuncio.fecha:%Y-%m-%d} ({anuncio.id})\n"
        f"Organismo: {anuncio.organismo}\n"
        f"Título: {anuncio.titulo}\n\n"
        f"TEXTO DEL ANUNCIO:\n{_recortar(texto, cfg.ia_max_caracteres)}"
    )
    cuerpo = {
        "model": cfg.ia_modelo,
        "max_tokens": 8000,
        "system": sistema,
        "messages": [{"role": "user", "content": usuario}],
        "output_config": {"format": {"type": "json_schema", "schema": ESQUEMA}},
    }
    cabeceras = {
        "x-api-key": cfg.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    for intento in range(3):
        r = requests.post(API_URL, headers=cabeceras, json=cuerpo, timeout=180)
        if r.status_code in (429, 500, 502, 503, 529):
            log.warning("API ocupada (%s), reintento %d", r.status_code, intento + 1)
            import time
            time.sleep(20 * (intento + 1))
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"Error de la API de Claude {r.status_code}: {r.text[:300]}")
        datos = r.json()
        if datos.get("stop_reason") == "max_tokens":
            cuerpo["max_tokens"] = 16000
            continue
        texto_json = next((b.get("text", "") for b in datos.get("content", [])
                           if b.get("type") == "text"), "")
        resultado = json.loads(texto_json)
        resultado["_modo"] = "ia"
        return resultado
    raise RuntimeError("La API de Claude no respondió tras varios intentos")


# ---------------------------------------------------------------------------
# Modo básico (sin clave de API): expresiones regulares, menos detalle.
# ---------------------------------------------------------------------------
_NUMEROS = {"diez": 10, "quince": 15, "veinte": 20, "treinta": 30, "un": 1, "uno": 1,
            "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
            "nueve": 9, "doce": 12, "cuarenta": 40, "cincuenta": 50}


def _num(s: str) -> int | None:
    s = s.lower().strip()
    if s.isdigit():
        return int(s)
    return _NUMEROS.get(s)


_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]


def _bases_bocm(texto: str) -> dict:
    """Busca 'Boletín Oficial de la Comunidad de Madrid» número 240, de 9 de octubre de 2026'."""
    m = re.search(r"Comunidad de Madrid\W{0,3}\s*(?:n[uú]mero|n\.?\s?[ºo°])\s*(\d+),?\s*de\s*(?:fecha\s*)?"
                  r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", texto, re.I)
    if not m or m.group(3).lower() not in _MESES:
        return {"numero": None, "fecha": None}
    fecha = dt.date(int(m.group(4)), _MESES.index(m.group(3).lower()) + 1, int(m.group(2)))
    return {"numero": int(m.group(1)), "fecha": fecha.isoformat()}


def analizar_basico(anuncio: Anuncio, texto: str, cfg: Config) -> dict:
    t = texto
    tl = t.lower()
    subgrupo = "DESCONOCIDO"
    for sg, pat in (("C1", r"subgrupo\s*c\s?1\b"), ("C2", r"subgrupo\s*c\s?2\b"),
                    ("AP", r"agrupaciones? profesionales"), ("A1", r"subgrupo\s*a\s?1\b"),
                    ("A2", r"subgrupo\s*a\s?2\b")):
        if re.search(pat, tl):
            subgrupo = sg
            break
    plazo = {"dias": None, "tipo": "desconocido", "cuenta_desde": "desconocido",
             "fecha_fin_explicita": None}
    m = re.search(r"plazo[^.]{0,200}?\b(\d+|diez|quince|veinte|treinta)\s+d[ií]as\s+(h[aá]biles|naturales)", tl)
    if m:
        plazo["dias"] = _num(m.group(1))
        plazo["tipo"] = "habiles" if m.group(2).startswith("h") else "naturales"
        cola = tl[m.end():m.end() + 250]
        if "bolet" in cola and "estado" in cola and anuncio.fuente == "BOCM":
            plazo["cuenta_desde"] = "extracto_boe"
        else:
            plazo["cuenta_desde"] = "esta_publicacion"
    mp = re.search(r"\b(\d{1,4})\s+plazas?\b", tl)
    temas = [int(x) for x in re.findall(r"(?:^|\n)\s*tema\s+(\d{1,3})\b", tl)]
    accesible = "si" if subgrupo in cfg.subgrupos else ("no" if subgrupo in ("A1", "A2", "B") else "dudoso")
    proceso = {
        "puesto": anuncio.titulo[:120], "cuerpo_escala": "", "subgrupo": subgrupo,
        "grupo_laboral_equivalente": None, "personal": "desconocido",
        "turno_libre": "promoción interna" not in tl or "libre" in tl,
        "plazas_libre": None, "plazas_total": int(mp.group(1)) if mp else None,
        "sistema": "concurso-oposicion" if "concurso-oposici" in tl else (
            "oposicion" if "oposici" in tl else "desconocido"),
        "titulacion_requerida": "", "requisitos_extra": "",
        "accesible": accesible, "motivo_accesible": "Detectado automáticamente (sin IA)",
        "url_inscripcion": None, "tasa_euros": None,
        "temario": {"disponible": bool(temas), "num_temas": max(temas) if temas else None,
                    "bloques": []},
        "ejercicios": [],
        "dificultad": {"nivel": 0, "explicacion": "Sin IA no se estima la dificultad."},
        "aspirantes": {"estimacion": "", "explicacion": ""},
    }
    return {
        "tipo_publicacion": "convocatoria", "resumen": anuncio.titulo,
        "plazo": plazo, "referencia_bases": None, "bases_bocm": _bases_bocm(t),
        "apertura_estimada": None, "procesos": [proceso], "_modo": "basico",
    }


def analizar(anuncio: Anuncio, texto: str, cfg: Config) -> dict:
    if cfg.ia_activada and cfg.anthropic_api_key:
        return analizar_con_claude(anuncio, texto, cfg)
    return analizar_basico(anuncio, texto, cfg)
