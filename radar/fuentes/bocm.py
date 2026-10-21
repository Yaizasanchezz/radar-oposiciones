"""BOCM (Boletín Oficial de la Comunidad de Madrid).

- RSS de los últimos 20 sumarios: https://www.bocm.es/sumarios.rss  (fecha -> nº de boletín)
- Sumario completo en una sola página: /print/boletin-completo/BOCM-AAAAMMDD/NNN
- Cada anuncio en JSON-LD (con el texto): /boletin/CM_Orden_BOCM/AAAA/MM/DD/BOCM-AAAAMMDD-N.json
El robots.txt del BOCM pide 10 segundos entre peticiones y excluye
/boletin/CM_Boletin_BOCM/ (boletín completo), así que no se usa.
"""
from __future__ import annotations

import datetime as dt
import io
import logging
import re

from bs4 import BeautifulSoup

from .. import filtros
from ..config import Config
from ..http import BloqueadoPorRobots, Cliente
from . import Anuncio

log = logging.getLogger(__name__)

BASE = "https://www.bocm.es"
RSS_SUMARIOS = BASE + "/sumarios.rss"
_MARCA = "§§CVE={}§§"
_RE_MARCA = re.compile(r"§§CVE=(BOCM-\d{8}-\d+)§§")
_RE_CVE_JSON = re.compile(r"(BOCM-(\d{8})-(\d+))\.json", re.I)
_RE_SECCION = re.compile(r"^(I|II|III|IV|V)\.\s+[A-ZÁÉÍÓÚÑ]")
_RE_SUBSECCION = re.compile(r"^([A-D])\)\s+(Disposiciones|Autoridades|Otras|Anuncios)", re.I)
_IGNORAR = {"pdf", "html", "epub", "xml", "json", "descargar", "sección:", "seccion:"}


def boletines_recientes(rss_xml: str) -> list[tuple[dt.date, int]]:
    """[(fecha, numero)] de los sumarios del RSS, sin repetir, del más antiguo al más nuevo."""
    vistos = {}
    for fecha, num in re.findall(r"boletin-completo/BOCM-(\d{8})/(\d+)", rss_xml, re.I):
        vistos[dt.datetime.strptime(fecha, "%Y%m%d").date()] = int(num)
    return sorted(vistos.items())


def url_sumario(fecha: dt.date, numero: int) -> str:
    return f"{BASE}/print/boletin-completo/BOCM-{fecha:%Y%m%d}/{numero}"


def url_json(cve: str) -> str:
    _, f, _ = cve.split("-")
    return f"{BASE}/boletin/CM_Orden_BOCM/{f[:4]}/{f[4:6]}/{f[6:]}/{cve}.json"


def url_pdf(cve: str) -> str:
    return url_json(cve)[:-5] + ".PDF"


def url_html(cve: str) -> str:
    return f"{BASE}/{cve.lower()}"


def entradas_sumario(html: str) -> list[dict]:
    """Extrae [{cve, titulo, seccion, organismo}] del sumario imprimible.

    No depende de la maquetación exacta: recorre el texto en orden, usando los
    enlaces .json de cada anuncio como separadores.
    """
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        m = _RE_CVE_JSON.search(a["href"])
        if m:
            a.replace_with(soup.new_string("\n" + _MARCA.format(m.group(1).upper()) + "\n"))
    lineas = [l.strip() for l in soup.get_text("\n").splitlines() if l.strip()]

    salida, buffer = [], []
    romano, letra, organismo = "", "", ""
    for linea in lineas:
        m = _RE_MARCA.search(linea)
        if m:
            titulo = re.sub(r"^\d{1,4}\s+", "", " ".join(buffer)).strip()
            if romano == "I" and letra == "B":
                seccion = "autoridades_personal"
            elif romano == "I" and letra == "A":
                seccion = "disposiciones_generales"
            elif romano == "III":
                seccion = "local"
            else:
                seccion = "otra"
            salida.append({"cve": m.group(1), "titulo": titulo, "seccion": seccion,
                           "organismo": organismo})
            buffer = []
            continue
        if linea.lower() in _IGNORAR:
            continue
        cabecera = _cabecera(linea)
        if cabecera:
            nuevo_romano, nueva_letra = cabecera
            if nuevo_romano:
                romano, letra = nuevo_romano, ""
            if nueva_letra:
                letra = nueva_letra
            organismo, buffer = "", []
            continue
        letras = re.sub(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ]", "", linea)
        if len(letras) >= 4 and letras == letras.upper() and not linea.startswith(("–", "-", "•")):
            organismo, buffer = linea, []
            continue
        buffer.append(linea)
    return salida


def _cabecera(linea: str) -> tuple[str, str] | None:
    """Reconoce cabeceras de sección: "Sección: I. COMUNIDAD DE MADRID | B) Autoridades y
    Personal", o sus trozos sueltos ("I. COMUNIDAD DE MADRID", "| B) Autoridades y Personal")."""
    texto = re.sub(r"^secci[oó]n:\s*", "", linea, flags=re.I).strip()
    es_seccion = texto != linea.strip()
    romano = letra = ""
    for parte in (p.strip() for p in texto.split("|")):
        if not parte:
            continue
        cabeza = parte.split(".", 1)[0]
        if _RE_SECCION.match(parte) and cabeza in {"I", "II", "III", "IV", "V"} \
                and parte.split(".", 1)[1] == parte.split(".", 1)[1].upper():
            romano = cabeza
            continue
        ms = _RE_SUBSECCION.match(parte)
        if ms:
            letra = ms.group(1).upper()
    if romano or letra:
        return romano, letra
    return ("", "") if es_seccion and not texto else None


def anuncios_de_sumario(html: str, fecha: dt.date, cfg: Config) -> list[Anuncio]:
    salida = []
    for e in entradas_sumario(html):
        ambito = filtros.ambito_bocm(e["seccion"], e["titulo"], e["organismo"], cfg)
        if not ambito or not filtros.parece_convocatoria(e["titulo"]):
            continue
        organismo = e["organismo"]
        if e["seccion"] == "local":
            ayto = cfg.ayuntamiento_por_clave(ambito)
            organismo = f"Ayuntamiento de {ayto.nombre}" if ayto else organismo
        salida.append(Anuncio(
            id=e["cve"], fuente="BOCM", fecha=fecha, titulo=e["titulo"],
            organismo=organismo or "Comunidad de Madrid", ambito=ambito,
            url=url_html(e["cve"]), url_texto=url_json(e["cve"]), url_pdf=url_pdf(e["cve"]),
            seccion=e["seccion"],
        ))
    return salida


def obtener_anuncios(cliente: Cliente, cfg: Config,
                     fechas: set[dt.date]) -> tuple[dict[dt.date, list[Anuncio]], set[dt.date]]:
    """Descarga los sumarios del BOCM de las fechas pedidas que sigan en el RSS.

    Devuelve ({fecha: anuncios}, fechas que tienen boletín según el RSS).
    """
    rss = cliente.get(RSS_SUMARIOS, accept="application/rss+xml").text
    boletines = boletines_recientes(rss)
    resultado = {}
    for fecha, numero in boletines:
        if fecha not in fechas:
            continue
        try:
            html = cliente.get(url_sumario(fecha, numero), accept="text/html").text
        except BloqueadoPorRobots:
            log.warning("robots.txt no permite leer el sumario BOCM %s", fecha)
            continue
        except Exception as e:  # se reintentará en la próxima ejecución
            log.error("BOCM %s: no se pudo leer el sumario (%s)", fecha, e)
            continue
        resultado[fecha] = anuncios_de_sumario(html, fecha, cfg)
    return resultado, {f for f, _ in boletines}


def texto_pdf(contenido: bytes) -> str:
    from pypdf import PdfReader

    lector = PdfReader(io.BytesIO(contenido))
    return "\n".join((p.extract_text() or "") for p in lector.pages)


def texto_completo(cliente: Cliente, anuncio: Anuncio) -> str:
    texto = ""
    try:
        r = cliente.get(anuncio.url_texto, accept="application/ld+json, application/json")
        texto = (r.json() or {}).get("text", "") or ""
    except BloqueadoPorRobots:
        log.info("JSON de %s excluido por robots.txt", anuncio.id)
    except ValueError:
        log.warning("JSON no válido en %s", anuncio.id)
    # El JSON a veces no incluye anexos/tablas (donde suele estar el temario):
    # si es corto, se completa con el PDF.
    if len(texto) < 6000 and anuncio.url_pdf:
        try:
            r = cliente.get(anuncio.url_pdf, accept="application/pdf")
            pdf = texto_pdf(r.content)
            if len(pdf) > len(texto):
                texto = pdf
        except BloqueadoPorRobots:
            log.info("PDF de %s excluido por robots.txt", anuncio.id)
        except Exception as e:  # PDF dañado, etc.
            log.warning("No se pudo leer el PDF de %s: %s", anuncio.id, e)
    return texto
