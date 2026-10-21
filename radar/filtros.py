"""Filtros rápidos (sin IA) para descartar lo que claramente no interesa.

La idea es dejar pasar todo lo que *podría* ser una oposición accesible y que
la IA decida el resto: más vale un falso positivo (la IA lo descarta) que
perder una convocatoria.
"""
from __future__ import annotations

import re
import unicodedata

from .config import Config


def normalizar(texto: str) -> str:
    """minúsculas, sin tildes y con espacios simples."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t.lower()).strip()


# Señales de que el anuncio abre o anuncia un proceso selectivo
_SI = re.compile(
    r"convoca|convocatoria|proceso[s]? selectivo|pruebas? selectiva|bases|"
    r"oferta (de )?empleo publico|plazas?\b|bolsa de (empleo|trabajo)|"
    r"ingreso,? por el sistema|acceso libre|turno libre"
)

# Señales de que NO es para ti (o no es una apertura de plazo)
_NO = re.compile(
    r"concurso de traslados|libre designacion|concurso (especifico|general|de meritos)|"
    r"provision de puestos|comision de servicios|se nombra|nombramiento|"
    r"se resuelve|resuelve (la|el)|relacion (definitiva|provisional) de aprobados|"
    r"lista[s]? (definitiva|provisional)e?s? de (admitidos|aprobados|excluidos)|"
    r"admitidos y excluidos|se aprueba(n)? la(s)? lista|fecha,? hora y lugar|"
    r"tribunal (calificador|de seleccion)|correccion de errores|"
    r"personal docente|cuerpo de maestros|profesores?\b|catedratic|"
    r"profesorado|personal docente e investigador|ayudante doctor|"
    r"facultativo especialista|medico|enfermer|jueces|magistrad|notari|registrador|"
    r"emplazamiento|recurso contencioso|\bcese\b|jubilacion|subvencion|"
    r"relacion de puestos de trabajo|adjudica|"
    # listas, correcciones y trámites de procesos ya convocados (vistos en el BOE/BOCM reales)
    r"admitid[oa]s|aspirantes propuest|exclusion de aspirantes|calificaciones|corrig|"
    r"ampliacion del numero de plazas|modifica el numero de plazas|declara la urgencia|"
    r"requiere documentacion|modifica la composicion|reservista voluntario|letrados|"
    r"relacion de (personas )?aprobad"
)

# Categorías del sumario del BOCM que nunca abren un plazo
_NO_CATEGORIA = re.compile(r"^(aspirantes proceso selectivo|resolucion proceso selectivo|"
                           r"comision permanente|tribunal|nombramiento)")

_SOLO_PROMOCION_INTERNA = re.compile(r"promocion interna")
_LIBRE = re.compile(r"acceso libre|turno libre|sistema general de acceso libre|libre\b")


def parece_convocatoria(titulo: str) -> bool:
    t = normalizar(titulo)
    if _NO_CATEGORIA.match(t) or not _SI.search(t) or _NO.search(t):
        return False
    if _SOLO_PROMOCION_INTERNA.search(t) and not _LIBRE.search(t):
        return False
    return True


def es_oferta_empleo_publico(titulo: str) -> bool:
    return re.search(r"oferta (de )?empleo publico", normalizar(titulo)) is not None


# --- ámbito -------------------------------------------------------------
_RE_AGE = re.compile(
    r"^(ministerio|cortes generales|tribunal constitucional|consejo general del poder judicial|"
    r"tribunal de cuentas|consejo de estado|defensor del pueblo|presidencia del gobierno|"
    r"junta electoral central|consejo de seguridad nuclear|comision nacional|"
    r"banco de espana|agencia estatal)"
)


def ambito_boe(departamento: str, titulo: str, cfg: Config) -> str | None:
    """Devuelve la clave de ámbito de un anuncio del BOE, o None si no interesa."""
    dep = normalizar(departamento)
    tit = normalizar(titulo)
    if dep == "administracion local":
        for a in cfg.ayuntamientos:
            if _menciona_ayuntamiento(tit, a.nombre):
                return a.clave
        return None
    if dep == "comunidad de madrid":
        return "comunidad_madrid" if cfg.comunidad_madrid else None
    if dep == "universidades":
        if cfg.universidades_madrid and _universidad_madrid(tit):
            return "universidad_madrid"
        return None
    if cfg.estatal and _RE_AGE.match(dep):
        return "estatal"
    return None


def _menciona_ayuntamiento(texto_norm: str, nombre: str) -> bool:
    n = normalizar(nombre)
    # "ayuntamiento de madrid" pero no "ayuntamiento de madridejos"
    return re.search(rf"ayuntamiento de {re.escape(n)}(?![a-z])", texto_norm) is not None


_UNIS_MADRID = ("complutense", "autonoma de madrid", "carlos iii", "rey juan carlos",
                "alcala", "politecnica de madrid")


def _universidad_madrid(texto_norm: str) -> bool:
    return any(u in texto_norm for u in _UNIS_MADRID)


def ambito_bocm(seccion: str, titulo: str, organismo: str, cfg: Config) -> str | None:
    """Ámbito de un anuncio del BOCM según su sección y título."""
    tit = normalizar(titulo)
    org = normalizar(organismo)
    if seccion == "local":
        # Títulos de la sección III: "– Alcorcón. Ofertas de empleo. Bases..."
        m = re.match(r"^[–\-•\s]*([^.]+)\.\s*([^.]+)\.", titulo.strip())
        municipio = normalizar(m.group(1)) if m else ""
        categoria = normalizar(m.group(2)) if m else ""
        if categoria and not re.search(r"ofertas? de empleo|personal", categoria):
            return None
        for a in cfg.ayuntamientos:
            if municipio == normalizar(a.nombre):
                return a.clave
        return None
    if seccion == "disposiciones_generales":
        # La Oferta de Empleo Público de la Comunidad se aprueba por decreto
        return "comunidad_madrid" if cfg.comunidad_madrid and es_oferta_empleo_publico(titulo) else None
    if seccion == "autoridades_personal":
        if "universidad" in org:
            return "universidad_madrid" if cfg.universidades_madrid else None
        return "comunidad_madrid" if cfg.comunidad_madrid else None
    return None


# --- pistas de subgrupo en el texto (para no gastar IA en lo que es A1/A2) ---
# Solo marcas de grupo/titulación (no palabras sueltas como "oficial", que aparece
# en "Boletín Oficial" y dejaría pasarlo todo).
_RE_GRUPO_OK = re.compile(
    r"subgrupo,? c ?1\b|subgrupo,? c ?2\b|grupo c\b|grupo c[12]\b|\(c[12]\)|"
    r"agrupaci[oó]n(es)? profesional(es)?|grupo e\b|"
    r"grupo (profesional )?(iii|iv|v|3|4|5|e ?[0-3]|d ?[1-3])\b|"
    r"bachiller|titulo de tecnico|tecnico superior|tecnico especialista|"
    r"graduado en educacion secundaria|graduado en e\.?s\.?o|graduado escolar|"
    r"certificado de escolaridad|sin titulacion|no se exige titulacion|"
    r"tramitacion procesal|auxilio judicial|escala basica|guardia civil"
)


def texto_menciona_grupos_accesibles(texto: str) -> bool:
    return _RE_GRUPO_OK.search(normalizar(texto[:400000])) is not None


def es_afin(texto: str, cfg: Config) -> bool:
    t = normalizar(texto)
    return any(normalizar(p) in t for p in cfg.palabras_afines)
