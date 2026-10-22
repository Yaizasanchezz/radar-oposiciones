"""Junta de Castilla-La Mancha: Portal de Empleo Público (empleopublico.castillalamancha.es).

El DOCM no permite programas automáticos (su robots.txt excluye sumario.do,
detalleDocumento.do y descargarArchivo.do), así que se usa el portal de empleo
público de la Junta, que tiene una página por proceso selectivo con sus datos
(cuerpo, plazas, turno) y todos sus documentos fechados: convocatoria, temario,
listas, etc.

- Listados: /procesos-selectivos/abiertos/<categoria> (turno libre, bolsas, policía local)
- Proceso:  /procesos-selectivos/abiertos/<categoria>/<slug>
La fecha del documento "Convocatoria" es la de su publicación en el DOCM, que
es cuando empieza a contar el plazo de solicitudes.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..config import Config
from ..filtros import normalizar
from ..http import BloqueadoPorRobots, Cliente
from . import Anuncio

log = logging.getLogger(__name__)

BASE = "https://empleopublico.castillalamancha.es"
LISTADOS = [
    "/procesos-selectivos/abiertos/turno-libre",
    "/procesos-selectivos-abiertos-constitucion-bolsas-de-trabajo",
    "/procesos-selectivos/abiertos/ampliacion-bolsas-de-trabajo",
    "/procesos-selectivos/abiertos/cuerpos-de-policia-local-de-castilla-la-mancha",
]
_RE_PROCESO = re.compile(r"/procesos-selectivos/abiertos/[^/?#]+/[^/?#]+/?$")
_RE_FECHA = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")

# Grupos por el título del proceso ("2025 - Cuerpo AUXILIAR - Auxiliar - Turno Libre")
_ACCESIBLE = re.compile(r"cuerpo auxiliar|cuerpo ejecutivo|grupo (iii|iv|v)\b|policia local|"
                        r"agrupaciones? profesional|subgrupo c[12]|\bc[12]\b|grupo c\b|grupo e\b|"
                        r"subgrupo b\b|grupo b\b")
_NO_ACCESIBLE = re.compile(r"cuerpo superior|cuerpo tecnico|grupo (i|ii)\b|\ba[12]\b|"
                           r"secretaria|intervencion|tesoreria|letrados|investigacion")


def accesible_por_titulo(titulo: str) -> bool | None:
    """True si el título indica C1/C2/AP o laboral III-V; False si A1/A2; None si no se sabe."""
    t = normalizar(titulo)
    if _ACCESIBLE.search(t):
        return True
    if _NO_ACCESIBLE.search(t):
        return False
    return None


def slug(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def procesos_de_listado(html: str, base: str = BASE) -> list[tuple[str, str]]:
    """[(url, título)] de los procesos enlazados en un listado."""
    soup = BeautifulSoup(html, "html.parser")
    vistos, salida = set(), []
    for a in soup.find_all("a", href=True):
        url = urljoin(base, a["href"]).split("#")[0]
        if not _RE_PROCESO.search(url) or url in vistos:
            continue
        titulo = (a.get("title") or a.get_text(" ", strip=True)).strip()
        if not titulo:
            continue
        vistos.add(url)
        salida.append((url, titulo))
    return salida


def _fecha_cerca(nodo) -> dt.date | None:
    """Busca una fecha dd/mm/aaaa en el elemento del enlace o justo antes."""
    actual = nodo
    for _ in range(3):  # el enlace, su contenedor y el contenedor de este
        if actual is None:
            break
        m = _RE_FECHA.search(actual.get_text(" ", strip=True))
        if m:
            return _a_fecha(m)
        actual = actual.parent
    previo = nodo.find_previous(string=_RE_FECHA)
    return _a_fecha(_RE_FECHA.search(previo)) if previo else None


def _a_fecha(m) -> dt.date | None:
    try:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def pagina_proceso(html: str, url: str) -> dict:
    """Datos de la página de un proceso: título, texto de los campos y documentos fechados."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    h1 = soup.find("h1")
    titulo = h1.get_text(" ", strip=True) if h1 else ""
    documentos = []
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        if ".pdf" not in href.lower():
            continue
        documentos.append({"etiqueta": a.get_text(" ", strip=True) or a.get("title", ""),
                           "url": href, "fecha": _fecha_cerca(a)})
    principal = soup.find("main") or soup.find(id="main-content") or soup.body or soup
    texto = "\n".join(l.strip() for l in principal.get_text("\n").splitlines() if l.strip())
    return {"titulo": titulo, "texto": texto, "documentos": documentos}


def _es(etiqueta: str, *palabras: str) -> bool:
    e = normalizar(etiqueta)
    return any(p in e for p in palabras)


def documento_convocatoria(docs: list[dict]) -> dict | None:
    """El documento con la convocatoria (no exámenes extraordinarios ni correcciones)."""
    candidatos = [d for d in docs if _es(d["etiqueta"], "convocatoria", "bases")
                  and not _es(d["etiqueta"], "examen", "extraordinari", "prueba", "correccion",
                              "llamamiento", "fecha")]
    candidatos.sort(key=lambda d: d["fecha"] or dt.date.min)
    return candidatos[0] if candidatos else None


def documento_temario(docs: list[dict]) -> dict | None:
    t = [d for d in docs if _es(d["etiqueta"], "temario", "programa")
         and not _es(d["etiqueta"], "correccion")]
    t.sort(key=lambda d: (0 if _es(d["etiqueta"], "individualizado") else 1))
    return t[0] if t else None


def obtener_anuncios(cliente: Cliente, cfg: Config, conocido, hoy: dt.date) -> list[Anuncio]:
    """Procesos de la Junta convocados recientemente que todavía no estén en la base de datos.

    `conocido(id)` dice si un proceso ya se revisó (para no descargarlo otra vez).
    """
    salida, vistos = [], set()
    limite = hoy - dt.timedelta(days=cfg.jccm_dias_convocatoria)
    for ruta in LISTADOS:
        try:
            html = cliente.get(BASE + ruta, accept="text/html").text
        except BloqueadoPorRobots:
            log.warning("JCCM: robots.txt no permite leer %s", ruta)
            continue
        except Exception as e:
            log.warning("JCCM: no se pudo leer el listado %s (%s)", ruta, e)
            continue
        for url, titulo in procesos_de_listado(html):
            ident = "JCCM-" + slug(url)
            if url in vistos or conocido(ident):
                continue
            vistos.add(url)
            # En los listados el enlace solo dice "Jurídica (2026)"; el cuerpo/grupo va en
            # el encabezado y en la dirección (".../2026-cuerpo-superior-juridica-turno-libre").
            if accesible_por_titulo(f"{titulo} {slug(url).replace('-', ' ')}") is False:
                continue
            try:
                pagina = pagina_proceso(cliente.get(url, accept="text/html").text, url)
            except Exception as e:
                log.warning("JCCM: no se pudo leer %s (%s)", url, e)
                continue
            conv = documento_convocatoria(pagina["documentos"])
            fecha = conv["fecha"] if conv and conv["fecha"] else None
            if fecha:
                antigua = fecha < limite
            else:
                # Sin fecha de convocatoria localizable: se decide por el año del título
                # ("2026 - Cuerpo AUXILIAR..."), para no perder procesos recientes.
                anios = [int(x) for x in re.findall(r"\b(20\d{2})\b", titulo)]
                antigua = not anios or max(anios) < hoy.year - 1
                log.warning("JCCM: no encuentro la fecha de la convocatoria en %s", url)
            temario = documento_temario(pagina["documentos"])
            salida.append(Anuncio(
                id=ident, fuente="JCCM", fecha=fecha or hoy,
                titulo=pagina["titulo"] or titulo, organismo="Junta de Comunidades de Castilla-La Mancha",
                ambito="castilla_la_mancha", url=url, url_texto=url,
                url_pdf=conv["url"] if conv else "", seccion="proceso",
                extra={"texto_pagina": pagina["texto"], "antigua": antigua,
                       "temario_pdf": temario["url"] if temario else "",
                       "sin_fecha": fecha is None,
                       "nota": f"Este proceso es SOLO: {pagina['titulo'] or titulo}. Si la convocatoria "
                               f"incluye otros cuerpos o categorías, ignóralos. "
                               + ("La fecha del boletín es la de publicación de la convocatoria en el "
                                  "DOCM: el plazo cuenta desde ella (cuenta_desde = esta_publicacion)."
                                  if fecha else
                                  "No se conoce la fecha de publicación en el DOCM: usa "
                                  "cuenta_desde = desconocido salvo que el texto dé una fecha de fin.")},
            ))
    return salida


def texto_completo(cliente: Cliente, anuncio: Anuncio) -> str:
    from .bocm import texto_pdf

    partes = ["DATOS DEL PROCESO (portal de empleo público de la Junta):", anuncio.extra.get("texto_pagina", "")]
    for etiqueta, url in (("CONVOCATORIA", anuncio.url_pdf), ("TEMARIO", anuncio.extra.get("temario_pdf"))):
        if not url:
            continue
        try:
            partes += [f"\n{etiqueta}:", texto_pdf(cliente.get(url, accept="application/pdf").content)]
        except BloqueadoPorRobots:
            log.info("JCCM: robots.txt no permite descargar %s", url)
        except Exception as e:
            log.warning("JCCM: no se pudo leer el PDF %s (%s)", url, e)
    return "\n".join(partes)
