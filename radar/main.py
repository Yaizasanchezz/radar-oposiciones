"""Ejecución diaria del radar.

    python -m radar.main              # revisa los últimos días, avisa y regenera la web
    python -m radar.main --dias 10    # revisa más días hacia atrás
    python -m radar.main --solo-web   # solo regenera docs/data.js
    python -m radar.main --sin-telegram
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys

from . import ia, procesos, telegram, web
from .config import RUTA_DB, RUTA_WEB, Config, ahora_madrid, cargar, hoy_madrid
from .db import DB
from .filtros import es_oferta_empleo_publico, texto_menciona_grupos_accesibles
from .fuentes import Anuncio, bocm, boe, bop_toledo, jccm
from .http import BloqueadoPorRobots, Cliente
from .plazos import Calendario

log = logging.getLogger("radar")

LECTORES = {"BOE": boe, "BOCM": bocm, "BOP Toledo": bop_toledo, "JCCM": jccm}
ORDEN_FUENTE = {"BOCM": 0, "BOP Toledo": 0, "JCCM": 1, "BOE": 2}  # bases antes que extractos


class Estado:
    """Resumen de cómo ha ido cada fuente (se guarda en data/estado.json)."""

    def __init__(self):
        self.fuentes: dict[str, dict] = {}

    def anotar(self, fuente: str, resultado: str, detalle: str = "", candidatos: int = 0):
        f = self.fuentes.setdefault(fuente, {"ok": 0, "errores": 0, "candidatos": 0, "avisos": []})
        if resultado == "ok":
            f["ok"] += 1
            f["candidatos"] += candidatos
        else:
            f["errores"] += 1
            if detalle and detalle not in f["avisos"]:
                f["avisos"].append(detalle[:200])
        if resultado == "robots":
            f["robots"] = True

    def alguna_ok(self) -> bool:
        return any(f["ok"] for f in self.fuentes.values())

    def guardar(self, ruta):
        ruta.write_text(json.dumps({"ejecucion": ahora_madrid().isoformat(timespec="minutes"),
                                    "fuentes": self.fuentes}, ensure_ascii=False, indent=1),
                        encoding="utf-8")


def recoger_anuncios(cliente: Cliente, cfg: Config, db: DB, fechas: list[dt.date],
                     hoy: dt.date, estado: Estado | None = None) -> tuple[list[Anuncio], dict, int]:
    """Descarga los sumarios pendientes.

    Devuelve (anuncios candidatos, {(fuente, fecha): nº candidatos}, nº de errores de lectura).
    """
    estado = estado or Estado()
    anuncios: list[Anuncio] = []
    revisadas: dict[tuple[str, dt.date], int] = {}
    errores = 0

    # --- BOE ---
    for f in fechas:
        if db.fecha_revisada("BOE", f):
            continue
        try:
            lista = boe.obtener_anuncios(cliente, f, cfg)
        except Exception as e:
            log.error("BOE %s: no se pudo leer el sumario (%s)", f, e)
            estado.anotar("BOE", "error", str(e))
            errores += 1
            continue
        if lista is None:
            if f < hoy:  # domingo o día sin BOE; hoy se reintenta más tarde
                db.marcar_fecha("BOE", f, "sin boletín")
            continue
        log.info("BOE %s: %d candidatos", f, len(lista))
        estado.anotar("BOE", "ok", candidatos=len(lista))
        anuncios += lista
        revisadas[("BOE", f)] = len(lista)

    # --- BOCM ---
    pendientes = {f for f in fechas if not db.fecha_revisada("BOCM", f)}
    if pendientes and (cfg.comunidad_madrid or cfg.ayuntamientos_de("bocm") or cfg.universidades_madrid):
        try:
            por_fecha, con_boletin = bocm.obtener_anuncios(cliente, cfg, pendientes)
        except Exception as e:
            log.error("BOCM: no se pudo leer el RSS (%s)", e)
            estado.anotar("BOCM", "error", str(e))
            por_fecha, con_boletin = {}, set()
            errores += 1
        for f, lista in por_fecha.items():
            log.info("BOCM %s: %d candidatos", f, len(lista))
            estado.anotar("BOCM", "ok", candidatos=len(lista))
            anuncios += lista
            revisadas[("BOCM", f)] = len(lista)
        if con_boletin:
            for f in pendientes - con_boletin:
                if min(con_boletin) < f < max(con_boletin):  # domingos y festivos
                    db.marcar_fecha("BOCM", f, "sin boletín")

    # --- BOP de Toledo (solo si el sitio permite programas automáticos) ---
    if cfg.ayuntamientos_de("bop_toledo"):
        for f in fechas:
            if f.weekday() >= 5 or db.fecha_revisada("BOP Toledo", f):
                continue
            try:
                lista = bop_toledo.obtener_anuncios(cliente, cfg, f)
            except BloqueadoPorRobots:
                log.warning("BOP Toledo: su robots.txt no permite programas automáticos; se usa "
                            "solo el BOE para Seseña/Illescas.")
                estado.anotar("BOP Toledo", "robots", "robots.txt no permite leerlo")
                break
            except Exception as e:
                log.warning("BOP Toledo %s: no se pudo leer (%s)", f, e)
                estado.anotar("BOP Toledo", "error", str(e))
                continue
            log.info("BOP Toledo %s: %d candidatos", f, len(lista))
            estado.anotar("BOP Toledo", "ok", candidatos=len(lista))
            anuncios += lista
            revisadas[("BOP Toledo", f)] = len(lista)

    # --- Junta de Castilla-La Mancha (portal de empleo público) ---
    if cfg.castilla_la_mancha:
        try:
            lista = jccm.obtener_anuncios(cliente, cfg, db.anuncio_conocido, hoy)
            log.info("JCCM: %d procesos nuevos en el portal", len(lista))
            estado.anotar("JCCM", "ok", candidatos=len(lista))
            anuncios += lista
        except BloqueadoPorRobots:
            log.warning("JCCM: robots.txt no permite leer el portal de empleo público")
            estado.anotar("JCCM", "robots", "robots.txt no permite leerlo")
        except Exception as e:
            log.error("JCCM: no se pudo leer el portal (%s)", e)
            estado.anotar("JCCM", "error", str(e))

    anuncios.sort(key=lambda a: (a.fecha, ORDEN_FUENTE.get(a.fuente, 9)))
    return anuncios, revisadas, errores


def bases_referenciadas(cliente: Cliente, cfg: Config, a: Anuncio, analisis: dict) -> list[Anuncio]:
    """Si un extracto del BOE remite a unas bases del BOCM o del BOP de Toledo, las localiza
    para sacar el temario."""
    ref = analisis.get("bases_publicadas") or analisis.get("bases_bocm") or {}
    boletin = ref.get("boletin", "BOCM")
    if a.fuente != "BOE" or a.ambito == "estatal" or not ref.get("fecha"):
        return []
    try:
        fecha = dt.date.fromisoformat(ref["fecha"])
        if boletin == "BOCM" and ref.get("numero"):
            html = cliente.get(bocm.url_sumario(fecha, int(ref["numero"])), accept="text/html").text
            encontrados = bocm.anuncios_de_sumario(html, fecha, cfg)
        elif boletin == "BOP_TOLEDO":
            encontrados = bop_toledo.obtener_anuncios(cliente, cfg, fecha)
        else:
            return []
    except Exception as e:
        log.info("No se pudieron localizar las bases en %s %s (%s)", boletin, ref, e)
        return []
    return [x for x in encontrados if x.ambito == a.ambito]


def procesar(anuncios: list[Anuncio], cliente: Cliente, cfg: Config, db: DB,
             cal: Calendario) -> tuple[list[tuple[int, str]], set]:
    eventos, fallidas = [], set()
    cola, vistos, i = list(anuncios), {a.id for a in anuncios}, 0
    while i < len(cola):
        a = cola[i]
        i += 1
        if db.anuncio_conocido(a.id):
            continue
        try:
            if a.extra.get("antigua"):
                db.guardar_anuncio(a, "descartado", "convocatoria antigua (ya pasó el plazo)")
                continue
            texto = LECTORES[a.fuente].texto_completo(cliente, a)
            if not texto.strip():
                raise ValueError("texto vacío")
            # Filtro barato solo para el Estado (muchos anuncios al día). Los de las
            # comunidades y ayuntamientos son pocos y sus extractos a veces no dicen el
            # subgrupo, así que siempre los lee la IA.
            if a.ambito == "estatal" and not es_oferta_empleo_publico(a.titulo) \
                    and not texto_menciona_grupos_accesibles(texto):
                db.guardar_anuncio(a, "descartado", "no menciona grupos C1/C2/AP")
                continue
            analisis = ia.analizar(a, texto, cfg)
            db.guardar_anuncio(a, "analizado", analisis=analisis)
            nuevos = procesos.registrar(db, cfg, cal, a, analisis)
            eventos += nuevos
            log.info("✓ %s %s → %d oposiciones (%s)", a.fuente, a.id, len(nuevos), a.titulo[:70])
            extra = [x for x in bases_referenciadas(cliente, cfg, a, analisis) if x.id not in vistos]
            if extra:
                log.info("  + bases: %s", ", ".join(x.id for x in extra))
                vistos.update(x.id for x in extra)
                cola[i:i] = extra
        except BloqueadoPorRobots:
            db.guardar_anuncio(a, "descartado", "excluido por robots.txt")
        except Exception as e:
            log.exception("✗ %s %s: %s", a.fuente, a.id, e)
            db.guardar_anuncio(a, "error", str(e)[:300])
            fallidas.add((a.fuente, a.fecha))
    return eventos, fallidas


def avisar(db: DB, cfg: Config, eventos: list[tuple[int, str]], hoy: dt.date, primera_vez: bool,
           nuevas_fuentes: list[str] | None = None):
    if primera_vez or nuevas_fuentes:
        ids = {pid for pid, tipo in eventos if tipo == "nueva"}
        filas = db.procesos() if primera_vez else [f for f in db.procesos() if f["id"] in ids]
        abiertas = [f for f in filas if procesos.estado(f, hoy) == "abierta"]
        if primera_vez:
            texto = (f"🌸 <b>Radar de oposiciones activado</b>\n"
                     f"He encontrado {len(filas)} oposiciones a las que puedes presentarte "
                     f"({len(abiertas)} con el plazo abierto ahora mismo).")
        else:
            texto = (f"🌸 <b>Radar ampliado</b>\nAhora también vigilo: {', '.join(nuevas_fuentes)}.\n"
                     f"He encontrado {len(filas)} oposiciones nuevas "
                     f"({len(abiertas)} con el plazo abierto ahora mismo).")
            for f in abiertas[:8]:
                fin = f" · hasta el {dt.date.fromisoformat(f['fin_plazo']):%d/%m}" if f["fin_plazo"] else ""
                texto += f"\n• {f['puesto']} ({cfg.nombre_ambito(f['ambito'])}){fin}"
        if cfg.url_web:
            texto += f'\n<a href="{cfg.url_web}">Míralas en la web</a>'
        texto += "\nA partir de ahora te aviso solo de las novedades."
        telegram.enviar(cfg, texto)
        for f in filas:
            for tipo in ("nueva", "abierta"):
                db.marcar_aviso(f["id"], tipo)
        eventos = [(pid, tipo) for pid, tipo in eventos if not db.aviso_enviado(pid, tipo)]

    for pid, tipo in eventos:
        if db.aviso_enviado(pid, tipo):
            continue
        fila = db.proceso(pid)
        if telegram.enviar(cfg, telegram.mensaje(fila, cfg, tipo, hoy)):
            db.marcar_aviso(pid, tipo)
            if procesos.estado(fila, hoy) == "abierta":
                db.marcar_aviso(pid, "abierta")

    for fila in db.procesos():
        if procesos.estado(fila, hoy) != "abierta" or not fila["fin_plazo"]:
            continue
        quedan = (dt.date.fromisoformat(fila["fin_plazo"]) - hoy).days
        if 0 <= quedan <= cfg.avisar_dias_antes_cierre and not db.aviso_enviado(fila["id"], "cierra_pronto"):
            if telegram.enviar(cfg, telegram.mensaje(fila, cfg, "cierra_pronto", hoy)):
                db.marcar_aviso(fila["id"], "cierra_pronto")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Radar de oposiciones (BOE, BOCM, BOP Toledo, JCCM)")
    ap.add_argument("--dias", type=int, help="días hacia atrás a revisar")
    ap.add_argument("--solo-web", action="store_true", help="solo regenerar la web")
    ap.add_argument("--sin-telegram", action="store_true", help="no mandar avisos")
    ap.add_argument("--sin-ia", action="store_true", help="modo básico sin Claude")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    cfg = cargar()
    if args.sin_ia:
        cfg.ia_activada = False
    if cfg.ia_activada and not cfg.anthropic_api_key:
        log.warning("Sin ANTHROPIC_API_KEY: se usa el modo básico (sin temario resumido "
                    "ni estimaciones). Mira el README para activarla.")
    db = DB(RUTA_DB)
    hoy = hoy_madrid()
    codigo = 0

    if not args.solo_web:
        primera_vez = db.esta_vacia()
        # Si se han añadido ámbitos (ayuntamientos, comunidades), se vuelven a mirar
        # los últimos días para no perderse lo que ya se publicó.
        ambitos = cfg.ambitos_validos()
        anteriores = json.loads(db.meta("ambitos") or "null")
        if anteriores is None and not primera_vez:  # bases de datos de la primera versión
            anteriores = ["estatal", "comunidad_madrid", "ayuntamiento_alcorcon", "ayuntamiento_madrid"]
        nuevas = [] if primera_vez or anteriores is None else [a for a in ambitos if a not in anteriores]
        if nuevas:
            log.info("Ámbitos nuevos: %s → reviso de nuevo los últimos %d días",
                     ", ".join(nuevas), cfg.dias_atras_primera_vez)
            db.olvidar_fechas_desde(hoy - dt.timedelta(days=cfg.dias_atras_primera_vez - 1))
        largo = primera_vez or bool(nuevas)
        n = args.dias or (cfg.dias_atras_primera_vez if largo else cfg.dias_atras_normal)
        fechas = [hoy - dt.timedelta(days=i) for i in range(n - 1, -1, -1)]
        cliente = Cliente(pausas={"www.boe.es": cfg.pausa_boe, "www.bocm.es": cfg.pausa_bocm,
                                  "empleopublico.castillalamancha.es": cfg.pausa_otros,
                                  "bop.diputoledo.es": cfg.pausa_otros})
        cal = Calendario(cfg.festivos_extra)
        estado = Estado()

        anuncios, revisadas, errores = recoger_anuncios(cliente, cfg, db, fechas, hoy, estado)
        eventos, fallidas = procesar(anuncios, cliente, cfg, db, cal)
        for (fuente, f), num in revisadas.items():
            if (fuente, f) not in fallidas:
                db.marcar_fecha(fuente, f, f"{num} candidatos")
        db.poner_meta("ambitos", json.dumps(ambitos))
        if not args.sin_telegram:
            avisar(db, cfg, eventos, hoy, primera_vez,
                   [cfg.nombre_ambito(a) for a in nuevas] if nuevas else None)
        log.info("Hecho: %d anuncios candidatos, %d novedades, %d con error",
                 len(anuncios), len(eventos), len(fallidas))
        estado.guardar(RUTA_DB.parent / "estado.json")
        if errores and not estado.alguna_ok():
            log.error("No se pudo leer ningún boletín. Se reintentará en la próxima ejecución.")
            codigo = 1  # GitHub marcará la ejecución en rojo y te avisará por correo

    total = web.exportar(db, cfg, hoy, RUTA_WEB / "data.js")
    log.info("Web actualizada con %d oposiciones", total)
    db.cerrar()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
