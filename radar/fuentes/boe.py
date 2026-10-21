"""BOE: API oficial de datos abiertos (sumario diario) + texto de cada disposición.

API: https://www.boe.es/datosabiertos/api/boe/sumario/AAAAMMDD  (Accept: application/json)
Sección 2B = "II. Autoridades y personal - B. Oposiciones y concursos".
El texto se lee de la versión HTML (txt.php), que el robots.txt del BOE permite;
la versión XML y los PDF de /boe/dias/ están excluidos para robots.
"""
from __future__ import annotations

import datetime as dt
import logging

from bs4 import BeautifulSoup

from .. import filtros
from ..config import Config
from ..http import Cliente
from . import Anuncio

log = logging.getLogger(__name__)

API = "https://www.boe.es/datosabiertos/api/boe/sumario/{fecha}"


def _lista(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _texto(v) -> str:
    if isinstance(v, dict):
        return v.get("texto", "")
    return v or ""


def items_del_sumario(datos: dict):
    """Recorre el JSON del sumario y produce (seccion, departamento, epigrafe, item)."""
    sumario = (datos.get("data") or {}).get("sumario") or {}
    for diario in _lista(sumario.get("diario")):
        for sec in _lista(diario.get("seccion")):
            for dep in _lista(sec.get("departamento")):
                for item in _lista(dep.get("item")):
                    yield sec, dep, None, item
                for epi in _lista(dep.get("epigrafe")):
                    for item in _lista(epi.get("item")):
                        yield sec, dep, epi, item


def anuncios_de_sumario(datos: dict, fecha: dt.date, cfg: Config) -> list[Anuncio]:
    salida = []
    for sec, dep, epi, item in items_del_sumario(datos):
        codigo = str(sec.get("codigo", "")).upper()
        titulo = item.get("titulo", "")
        departamento = dep.get("nombre", "")
        if codigo == "2B":
            if not filtros.parece_convocatoria(titulo):
                continue
        elif codigo == "1":
            # Ofertas de Empleo Público del Estado (anuncian plazas futuras)
            if not filtros.es_oferta_empleo_publico(titulo):
                continue
        else:
            continue
        ambito = filtros.ambito_boe(departamento, titulo, cfg)
        if not ambito:
            continue
        ident = item.get("identificador", "")
        salida.append(Anuncio(
            id=ident,
            fuente="BOE",
            fecha=fecha,
            titulo=titulo,
            organismo=departamento,
            ambito=ambito,
            url=item.get("url_html") or f"https://www.boe.es/diario_boe/txt.php?id={ident}",
            url_texto=item.get("url_html") or f"https://www.boe.es/diario_boe/txt.php?id={ident}",
            url_pdf=_texto(item.get("url_pdf")),
            seccion=codigo,
            extra={"epigrafe": (epi or {}).get("nombre", "")},
        ))
    return salida


def obtener_anuncios(cliente: Cliente, fecha: dt.date, cfg: Config) -> list[Anuncio] | None:
    """None si ese día no hubo BOE (domingos); lista (posiblemente vacía) si lo hubo."""
    r = cliente.get(API.format(fecha=fecha.strftime("%Y%m%d")), accept="application/json",
                    permitir_404=True)
    if r is None:
        return None
    datos = r.json()
    if str((datos.get("status") or {}).get("code", "200")) != "200":
        return None
    return anuncios_de_sumario(datos, fecha, cfg)


def extraer_texto_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    for ident in ("textoxslt", "DOdocText", "texto"):
        nodo = soup.find(id=ident)
        if nodo and len(nodo.get_text(strip=True)) > 200:
            return _limpiar(nodo.get_text("\n"))
    # Plan B: el bloque con más texto
    candidatos = soup.find_all(["div", "article", "main"]) or [soup]
    mejor = max(candidatos, key=lambda n: len(n.get_text(strip=True)))
    return _limpiar(mejor.get_text("\n"))


def _limpiar(t: str) -> str:
    lineas = [l.strip() for l in t.splitlines()]
    return "\n".join(l for l in lineas if l)


def texto_completo(cliente: Cliente, anuncio: Anuncio) -> str:
    r = cliente.get(anuncio.url_texto, accept="text/html")
    r.encoding = r.encoding or "utf-8"
    return extraer_texto_html(r.text)
