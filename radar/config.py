"""Carga de config.yaml y rutas del proyecto."""
from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
RUTA_CONFIG = RAIZ / "config.yaml"
RUTA_DB = RAIZ / "data" / "radar.db"
RUTA_WEB = RAIZ / "docs"

def ahora_madrid() -> dt.datetime:
    """Fecha y hora actuales en Madrid (los servidores de GitHub van en UTC)."""
    try:
        from zoneinfo import ZoneInfo

        return dt.datetime.now(ZoneInfo("Europe/Madrid")).replace(tzinfo=None)
    except Exception:  # pragma: no cover - sistemas sin datos de zonas horarias
        return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=1)


def hoy_madrid() -> dt.date:
    return ahora_madrid().date()


@dataclass
class Ayuntamiento:
    nombre: str
    clave: str
    url_inscripcion: str = ""
    boletin: str = "bocm"   # bocm | bop_toledo

    @property
    def region(self) -> str:
        return "clm" if self.boletin == "bop_toledo" else "madrid"


@dataclass
class Config:
    subgrupos: list[str]
    titulacion: str
    mis_titulos: list[str]
    palabras_afines: list[str]
    estatal: bool
    comunidad_madrid: bool
    castilla_la_mancha: bool
    ayuntamientos: list[Ayuntamiento]
    universidades_madrid: bool
    inscripcion_por_defecto: dict[str, str]
    ia_activada: bool
    ia_modelo: str
    ia_max_caracteres: int
    dias_atras_primera_vez: int
    dias_atras_normal: int
    pausa_boe: float
    pausa_bocm: float
    pausa_otros: float
    jccm_dias_convocatoria: int
    avisar_dias_antes_cierre: int
    ocultar_cerradas_tras_dias: int
    festivos_extra: list[dt.date] = field(default_factory=list)

    # --- secretos (variables de entorno, nunca en el YAML) ---
    @property
    def anthropic_api_key(self) -> str:
        crudo = os.environ.get("ANTHROPIC_API_KEY", "")
        m = re.search(r"sk-ant-[A-Za-z0-9_\-]+", re.sub(r"\s+", "", crudo))
        return m.group(0) if m else crudo.strip()

    @property
    def telegram_token(self) -> str:
        # Tolera que se haya pegado con texto o espacios alrededor ("Use this token...: 123:ABC")
        crudo = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        m = re.search(r"\d{5,}:[A-Za-z0-9_-]{20,}", crudo.replace(" ", ""))
        return m.group(0) if m else crudo.strip()

    @property
    def telegram_chat_id(self) -> str:
        m = re.search(r"-?\d{5,}", os.environ.get("TELEGRAM_CHAT_ID", ""))
        return m.group(0) if m else ""

    @property
    def url_web(self) -> str:
        return os.environ.get("RADAR_URL_WEB", "").strip()

    def ayuntamiento_por_clave(self, clave: str) -> Ayuntamiento | None:
        return next((a for a in self.ayuntamientos if a.clave == clave), None)

    def url_inscripcion_defecto(self, ambito: str) -> str:
        if ambito in self.inscripcion_por_defecto:
            return self.inscripcion_por_defecto[ambito]
        ayto = self.ayuntamiento_por_clave(ambito)
        return ayto.url_inscripcion if ayto else ""

    def ambitos_validos(self) -> list[str]:
        v = []
        if self.estatal:
            v.append("estatal")
        if self.comunidad_madrid:
            v.append("comunidad_madrid")
        if self.castilla_la_mancha:
            v.append("castilla_la_mancha")
        v += [a.clave for a in self.ayuntamientos]
        if self.universidades_madrid:
            v.append("universidad_madrid")
        return v

    def nombre_ambito(self, clave: str) -> str:
        fijos = {
            "estatal": "Estado (AGE)",
            "comunidad_madrid": "Comunidad de Madrid",
            "castilla_la_mancha": "Castilla-La Mancha",
            "universidad_madrid": "Universidad (Madrid)",
        }
        if clave in fijos:
            return fijos[clave]
        ayto = self.ayuntamiento_por_clave(clave)
        return f"Ayto. {ayto.nombre}" if ayto else clave

    def region(self, ambito: str) -> str:
        """Región de festivos de un ámbito: 'madrid', 'clm' o 'estado'."""
        if ambito == "castilla_la_mancha":
            return "clm"
        if ambito in ("comunidad_madrid", "universidad_madrid"):
            return "madrid"
        ayto = self.ayuntamiento_por_clave(ambito)
        return ayto.region if ayto else "estado"

    def ayuntamientos_de(self, boletin: str) -> list[Ayuntamiento]:
        return [a for a in self.ayuntamientos if a.boletin == boletin]


def _fecha(v) -> dt.date:
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v))


def cargar(ruta: Path = RUTA_CONFIG) -> Config:
    with open(ruta, encoding="utf-8") as f:
        c = yaml.safe_load(f) or {}
    perfil = c.get("perfil", {})
    amb = c.get("ambitos", {})
    ia = c.get("ia", {})
    ej = c.get("ejecucion", {})
    return Config(
        subgrupos=[s.upper() for s in perfil.get("subgrupos", ["C1", "C2", "AP"])],
        titulacion=perfil.get("titulacion", "Técnico Superior"),
        mis_titulos=list(perfil.get("mis_titulos") or []),
        palabras_afines=[p.lower() for p in perfil.get("palabras_afines") or []],
        estatal=bool(amb.get("estatal", True)),
        comunidad_madrid=bool(amb.get("comunidad_madrid", True)),
        castilla_la_mancha=bool(amb.get("castilla_la_mancha", False)),
        ayuntamientos=[Ayuntamiento(**a) for a in c.get("ayuntamientos") or []],
        universidades_madrid=bool(c.get("universidades_madrid", False)),
        inscripcion_por_defecto=dict(c.get("inscripcion_por_defecto") or {}),
        ia_activada=bool(ia.get("activada", True)),
        ia_modelo=ia.get("modelo", "claude-haiku-5-5"),
        ia_max_caracteres=int(ia.get("max_caracteres_texto", 200000)),
        dias_atras_primera_vez=int(ej.get("dias_atras_primera_vez", 30)),
        dias_atras_normal=int(ej.get("dias_atras_normal", 4)),
        pausa_boe=float(ej.get("pausa_boe_segundos", 2)),
        pausa_bocm=float(ej.get("pausa_bocm_segundos", 10)),
        pausa_otros=float(ej.get("pausa_otros_segundos", 3)),
        jccm_dias_convocatoria=int(ej.get("jccm_dias_convocatoria", 60)),
        avisar_dias_antes_cierre=int(ej.get("avisar_dias_antes_cierre", 3)),
        ocultar_cerradas_tras_dias=int(ej.get("ocultar_cerradas_tras_dias", 60)),
        festivos_extra=[_fecha(d) for d in c.get("festivos_extra") or []],
    )
