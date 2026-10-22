"""BOP de Toledo (Boletín Oficial de la Provincia de Toledo, bop.diputoledo.es).

Aquí publican sus bases los ayuntamientos de la provincia (Seseña, Illescas...).
El plazo de solicitudes se abre después, con el extracto en el BOE, que el radar
lee siempre; el BOP sirve para enterarse antes y para sacar el temario.

- Resumen de un día: /webEbop/ebopResumen.jsp?publication_date=dd/mm/aaaa&publication_date_to=dd/mm/aaaa
- Cada anuncio en PDF: /webEbop/DocGet?id=...&insert_number=N&insert_year=AAAA

Se respeta el robots.txt del sitio: si no permite programas automáticos, esta
fuente se salta (y se anota en data/estado.json) y el radar sigue con el BOE.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..config import Config
from ..filtros import normalizar
from ..http import Cliente
from . import Anuncio

log = logging.getLogger(__name__)

BASE = "https://bop.diputoledo.es/webEbop/"
_RE_DOC = re.compile(r"DocGet\?[^\"']*insert_number=(\d+)[^\"']*insert_year=(\d{4})", re.I)
_RE_INTERES = re.compile(r"personal|selectiv|oposici|plazas?\b|bolsa|convocatoria|empleo|"
                         r"funcionari|laboral|bases")
_RE_NO = re.compile(r"ordenanza|presupuesto|urbanis|licencia|tribut|padron|subvenci|"
                    r"cuenta general|contrat|admitidos|aprobados|nombramiento|tribunal")


def url_resumen(fecha: dt.date) -> str:
    f = fecha.strftime("%d/%m/%Y")
    return f"{BASE}ebopResumen.jsp?publication_date={f}&publication_date_to={f}"


def _contexto(a) -> str:
    """Texto del bloque del anuncio: sube por los contenedores hasta encontrar el organismo."""
    actual, texto = a, a.get_text(" ", strip=True)
    for _ in range(4):
        actual = actual.parent
        if actual is None:
            break
        t = actual.get_text(" ", strip=True)
        if len(t) > 1500:  # ya es la página entera
            break
        texto = t
        if "ayuntamiento" in normalizar(t):
            break
    return texto


def entradas_resumen(html: str, cfg: Config, fecha: dt.date) -> list[Anuncio]:
    soup = BeautifulSoup(html, "html.parser")
    aytos = cfg.ayuntamientos_de("bop_toledo")
    salida, vistos = [], set()
    for a in soup.find_all("a", href=True):
        m = _RE_DOC.search(a["href"])
        if not m or m.groups() in vistos:
            continue
        ctx = _contexto(a)
        n = normalizar(ctx)
        ayto = next((x for x in aytos if re.search(rf"\b{re.escape(normalizar(x.nombre))}\b", n)), None)
        if not ayto or not _RE_INTERES.search(n) or _RE_NO.search(n):
            continue
        vistos.add(m.groups())
        numero, anio = m.groups()
        salida.append(Anuncio(
            id=f"BOPTO-{anio}-{numero}", fuente="BOP Toledo", fecha=fecha,
            titulo=re.sub(r"\s+", " ", ctx)[:300], organismo=f"Ayuntamiento de {ayto.nombre}",
            ambito=ayto.clave, url=urljoin(BASE, a["href"]), url_texto=urljoin(BASE, a["href"]),
            url_pdf=urljoin(BASE, a["href"]), seccion="local",
        ))
    return salida


def obtener_anuncios(cliente: Cliente, cfg: Config, fecha: dt.date) -> list[Anuncio]:
    r = cliente.get(url_resumen(fecha), accept="text/html")
    return entradas_resumen(r.text, cfg, fecha)


def texto_completo(cliente: Cliente, anuncio: Anuncio) -> str:
    from .bocm import texto_pdf

    r = cliente.get(anuncio.url_pdf, accept="application/pdf")
    if r.content[:4] == b"%PDF":
        return texto_pdf(r.content)
    return BeautifulSoup(r.text, "html.parser").get_text("\n")
