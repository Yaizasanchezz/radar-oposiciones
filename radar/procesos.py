"""Convierte los análisis de anuncios en oposiciones (procesos) y calcula su estado.

Una misma oposición suele aparecer varias veces: en la Oferta de Empleo Público,
en las bases (BOCM) y en el extracto (BOE) que abre el plazo. Aquí se juntan
para que en la web salga una sola tarjeta que se va completando.
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import re

from .config import Config, ahora_madrid
from .db import DB
from .filtros import es_afin, normalizar
from .fuentes import Anuncio
from .plazos import Calendario

_VACIAS = {"de", "del", "la", "las", "el", "los", "y", "e", "en", "a", "cuerpo", "escala",
           "subescala", "categoria", "plaza", "plazas", "puesto", "funcionario", "funcionaria",
           "laboral", "personal", "administracion", "estado", "ayuntamiento", "comunidad",
           "madrid", "o", "a"}


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", normalizar(s)) if t not in _VACIAS and len(t) > 1}


def similitud(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    jaccard = len(ta & tb) / len(ta | tb)
    seq = difflib.SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return max(jaccard, seq)


def _subgrupos_compatibles(a: str | None, b: str | None) -> bool:
    a, b = (a or "DESCONOCIDO"), (b or "DESCONOCIDO")
    return a == b or "DESCONOCIDO" in (a, b) or "LABORAL" in (a, b)


def _fecha(s: str | None) -> dt.date | None:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _texto_plazo(plazo: dict) -> str:
    dias, tipo = plazo.get("dias"), plazo.get("tipo")
    if not dias or tipo == "desconocido":
        return ""
    unidad = {"habiles": "días hábiles", "naturales": "días naturales", "meses": "meses"}[tipo]
    return f"{dias} {unidad}"


# ---------------------------------------------------------------------------
def _buscar_existente(db: DB, anuncio: Anuncio, p: dict, tipo_pub: str):
    mejor, mejor_sim = None, 0.0
    for fila in db.procesos(anuncio.ambito):
        enlaces = json.loads(fila["enlaces"])
        if any(e["id"] == anuncio.id for e in enlaces):
            # el mismo anuncio procesado otra vez (los demás puestos del anuncio no cuentan)
            if fila["subgrupo"] == p.get("subgrupo") and similitud(fila["puesto"], p["puesto"]) >= 0.9:
                return fila
            continue
        if not _subgrupos_compatibles(fila["subgrupo"], p["subgrupo"]):
            continue
        fin = _fecha(fila["fin_plazo"])
        if fin and anuncio.fecha > fin + dt.timedelta(days=30):
            continue  # ya cerró hace tiempo: esto es una edición nueva
        creado = _fecha(fila["fecha_publicacion"])
        if creado and (anuncio.fecha - creado).days > 900:
            continue
        # Una convocatoria ya abierta no se mezcla con otra convocatoria distinta
        if fila["inicio_plazo"] and tipo_pub == "convocatoria" and not fila["pendiente_extracto"]:
            continue
        datos = json.loads(fila["datos"])
        sim = max(similitud(fila["puesto"], p["puesto"]),
                  similitud(datos.get("cuerpo_escala", ""), p.get("cuerpo_escala", "")) * 0.95)
        if sim > mejor_sim:
            mejor, mejor_sim = fila, sim
    return mejor if mejor_sim >= 0.75 else None


def _fusionar_datos(viejo: dict, nuevo: dict) -> dict:
    r = dict(viejo)
    for k, v in nuevo.items():
        if k == "temario":
            vt = viejo.get("temario") or {}
            if v.get("disponible") and (not vt.get("disponible") or
                                        (v.get("num_temas") or 0) > (vt.get("num_temas") or 0)):
                r[k] = v
        elif k == "ejercicios":
            if len(v or []) > len(viejo.get("ejercicios") or []):
                r[k] = v
        elif k == "dificultad":
            if (v or {}).get("nivel") and (not (viejo.get(k) or {}).get("nivel")
                                           or (nuevo.get("temario") or {}).get("disponible")):
                r[k] = v
        elif k == "aspirantes":
            if (v or {}).get("estimacion") and not (viejo.get(k) or {}).get("estimacion"):
                r[k] = v
        elif v not in (None, "", [], {}) and viejo.get(k) in (None, "", [], {}, "DESCONOCIDO", "desconocido"):
            r[k] = v
    return r


def registrar(db: DB, cfg: Config, cal: Calendario, anuncio: Anuncio, analisis: dict) -> list[tuple[int, str]]:
    """Guarda/actualiza los procesos de un anuncio. Devuelve eventos [(id, 'nueva'|'abierta')]."""
    eventos = []
    tipo_pub = analisis.get("tipo_publicacion", "otro")
    plazo = analisis.get("plazo") or {}
    ahora = ahora_madrid().isoformat(timespec="seconds")
    enlace = {"fuente": anuncio.fuente, "id": anuncio.id, "fecha": anuncio.fecha.isoformat(),
              "url": anuncio.url, "titulo": anuncio.titulo, "tipo": tipo_pub}

    inicio = fin = None
    if plazo.get("cuenta_desde") == "esta_publicacion":
        if plazo.get("dias") and plazo.get("tipo") != "desconocido":
            inicio, fin = cal.fin_plazo(anuncio.fecha, plazo["dias"], plazo["tipo"])
        explicita = _fecha(plazo.get("fecha_fin_explicita"))
        if explicita and explicita >= anuncio.fecha:
            inicio, fin = inicio or anuncio.fecha + dt.timedelta(days=1), explicita
        if inicio is None:
            inicio = anuncio.fecha + dt.timedelta(days=1)
    pendiente = 1 if plazo.get("cuenta_desde") == "extracto_boe" and not inicio else 0
    es_oep = 1 if tipo_pub == "oferta_empleo_publico" else 0

    for p in analisis.get("procesos") or []:
        if p.get("accesible") == "no":
            continue
        url_insc = p.get("url_inscripcion") or cfg.url_inscripcion_defecto(anuncio.ambito)
        plazas = p.get("plazas_libre") or p.get("plazas_total")
        existente = _buscar_existente(db, anuncio, p, tipo_pub)

        if existente is None:
            pid = db.insertar_proceso({
                "clave": normalizar(f"{anuncio.ambito}|{p['puesto']}"),
                "ambito": anuncio.ambito,
                "organismo": anuncio.organismo,
                "puesto": p["puesto"],
                "subgrupo": p.get("subgrupo"),
                "datos": json.dumps({**p, "resumen": analisis.get("resumen", ""),
                                     "afin": es_afin(f"{p['puesto']} {p.get('cuerpo_escala', '')}", cfg),
                                     "modo": analisis.get("_modo", "")}, ensure_ascii=False),
                "accesible": p.get("accesible", "dudoso"),
                "plazas": plazas,
                "fecha_publicacion": anuncio.fecha.isoformat(),
                "fecha_boe": anuncio.fecha.isoformat() if anuncio.fuente == "BOE" else None,
                "inicio_plazo": inicio.isoformat() if inicio else None,
                "fin_plazo": fin.isoformat() if fin else None,
                "plazo_texto": _texto_plazo(plazo),
                "pendiente_extracto": pendiente,
                "apertura_estimada": analisis.get("apertura_estimada"),
                "es_oep": es_oep,
                "url_inscripcion": url_insc,
                "enlaces": json.dumps([enlace], ensure_ascii=False),
                "creado": ahora,
                "actualizado": ahora,
            })
            eventos.append((pid, "nueva"))
            continue

        # --- fusionar con la oposición que ya teníamos ---
        enlaces = json.loads(existente["enlaces"])
        if not any(e["id"] == anuncio.id for e in enlaces):
            enlaces.append(enlace)
        datos = _fusionar_datos(json.loads(existente["datos"]), p)
        cambios = {
            "datos": json.dumps(datos, ensure_ascii=False),
            "enlaces": json.dumps(sorted(enlaces, key=lambda e: e["fecha"]), ensure_ascii=False),
            "actualizado": ahora,
            "plazas": existente["plazas"] or plazas,
            "accesible": "si" if "si" in (existente["accesible"], p.get("accesible")) else "dudoso",
        }
        if anuncio.fuente == "BOE" and not existente["fecha_boe"]:
            cambios["fecha_boe"] = anuncio.fecha.isoformat()
        if p.get("url_inscripcion"):
            cambios["url_inscripcion"] = p["url_inscripcion"]
        if inicio and not existente["inicio_plazo"]:
            cambios.update(inicio_plazo=inicio.isoformat(), fin_plazo=fin.isoformat() if fin else None,
                           pendiente_extracto=0, es_oep=0, plazo_texto=_texto_plazo(plazo)
                           or existente["plazo_texto"])
            eventos.append((existente["id"], "abierta"))
        elif pendiente and existente["es_oep"]:
            cambios.update(pendiente_extracto=1, es_oep=0,
                           plazo_texto=_texto_plazo(plazo) or existente["plazo_texto"])
        if tipo_pub != "oferta_empleo_publico" and existente["es_oep"] and not inicio and not pendiente:
            cambios["es_oep"] = 0
        if analisis.get("apertura_estimada") and not (inicio or existente["inicio_plazo"]):
            cambios["apertura_estimada"] = analisis["apertura_estimada"]
        db.actualizar_proceso(existente["id"], cambios)
    return eventos


# ---------------------------------------------------------------------------
def estado(fila, hoy: dt.date) -> str:
    inicio, fin = _fecha(fila["inicio_plazo"]), _fecha(fila["fin_plazo"])
    if inicio:
        if hoy < inicio:
            return "proxima"
        if fin:
            return "abierta" if hoy <= fin else "cerrada"
        return "abierta" if (hoy - inicio).days <= 30 else "cerrada"
    if fila["pendiente_extracto"]:
        return "proxima"
    if fila["es_oep"]:
        return "prevista"
    return "consultar"
