"""Exporta los procesos a docs/data.js para la web estática."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from urllib.parse import quote_plus

from .config import Config, ahora_madrid
from .db import DB
from .procesos import estado

ORDEN_ESTADO = {"abierta": 0, "proxima": 1, "prevista": 2, "consultar": 3, "cerrada": 4}


def exportar(db: DB, cfg: Config, hoy: dt.date, ruta: Path) -> int:
    items = []
    for f in db.procesos():
        est = estado(f, hoy)
        fin = f["fin_plazo"]
        if est == "cerrada" and fin and (hoy - dt.date.fromisoformat(fin)).days > cfg.ocultar_cerradas_tras_dias:
            continue
        datos = json.loads(f["datos"])
        items.append({
            "id": f["id"],
            "puesto": f["puesto"],
            "cuerpo": datos.get("cuerpo_escala", ""),
            "organismo": f["organismo"],
            "ambito": f["ambito"],
            "ambitoNombre": cfg.nombre_ambito(f["ambito"]),
            "subgrupo": f["subgrupo"],
            "grupoLaboral": datos.get("grupo_laboral_equivalente"),
            "personal": datos.get("personal"),
            "sistema": datos.get("sistema"),
            "plazas": f["plazas"],
            "accesible": f["accesible"],
            "motivoAccesible": datos.get("motivo_accesible", ""),
            "titulacion": datos.get("titulacion_requerida", ""),
            "requisitos": datos.get("requisitos_extra", ""),
            "estado": est,
            "publicado": f["fecha_publicacion"],
            "publicadoBOE": f["fecha_boe"],
            "inicioPlazo": f["inicio_plazo"],
            "finPlazo": fin,
            "plazoTexto": f["plazo_texto"],
            "aperturaEstimada": f["apertura_estimada"],
            "urlInscripcion": f["url_inscripcion"],
            "tasa": datos.get("tasa_euros"),
            "enlaces": json.loads(f["enlaces"]),
            "resumen": datos.get("resumen", ""),
            "temario": datos.get("temario") or {},
            "ejercicios": datos.get("ejercicios") or [],
            "dificultad": datos.get("dificultad") or {},
            "aspirantes": datos.get("aspirantes") or {},
            "afin": bool(datos.get("afin")),
            "nuevo": (hoy - dt.date.fromisoformat(f["creado"][:10])).days <= 2,
            "modo": datos.get("modo", ""),
        })
    items.sort(key=lambda i: (ORDEN_ESTADO.get(i["estado"], 9),
                              i["finPlazo"] or "9999", -(int(i["publicado"].replace("-", "")))))
    contenido = {
        "actualizado": ahora_madrid().strftime("%Y-%m-%d %H:%M"),
        "hoy": hoy.isoformat(),
        "ambitos": {c: cfg.nombre_ambito(c) for c in cfg.ambitos_validos()},
        "ayuntamientos": [{
            "clave": a.clave, "nombre": a.nombre, "boletin": a.boletin,
            "urlEmpleo": a.url_empleo or a.url_inscripcion,
            "urlBoletin": ("https://bop.diputoledo.es/webEbop/ebop.jsp?search=true&sort=publication_date+desc"
                           "&publisher_facet=" + quote_plus("AYUNTAMIENTO DE " + a.nombre.upper()))
                          if a.boletin == "bop_toledo" else "https://www.bocm.es/ultimo-bocm",
        } for a in cfg.ayuntamientos],
        "oposiciones": items,
    }
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("window.RADAR = " + json.dumps(contenido, ensure_ascii=False, indent=1) + ";\n",
                    encoding="utf-8")
    return len(items)
