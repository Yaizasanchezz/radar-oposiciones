"""Fuentes de datos: BOE y BOCM."""
from dataclasses import dataclass, field
import datetime as dt


@dataclass
class Anuncio:
    """Un anuncio de boletín que podría ser una oposición."""
    id: str                 # BOE-A-2026-12345 / BOCM-20261020-48
    fuente: str             # "BOE" | "BOCM"
    fecha: dt.date
    titulo: str
    organismo: str
    ambito: str             # clave de ámbito (estatal, comunidad_madrid, ayuntamiento_x...)
    url: str                # página para personas (HTML)
    url_texto: str = ""     # de dónde sacar el texto completo
    url_pdf: str = ""
    seccion: str = ""
    extra: dict = field(default_factory=dict)
