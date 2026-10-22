"""Base de datos SQLite.

- anuncios: cada anuncio de boletín revisado (para no leerlo ni pagar la IA dos veces).
- procesos: cada oposición (una misma oposición puede tener bases en el BOCM y
  extracto en el BOE: se guardan juntos para no repetir información).
- fechas_revisadas: qué días de cada boletín ya se han procesado.
- avisos: qué avisos de Telegram se han mandado (para no repetirlos).
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS anuncios (
    id TEXT PRIMARY KEY,
    fuente TEXT NOT NULL,
    fecha TEXT NOT NULL,
    titulo TEXT NOT NULL,
    organismo TEXT,
    ambito TEXT,
    url TEXT,
    estado TEXT NOT NULL DEFAULT 'pendiente',   -- pendiente | analizado | descartado | error
    motivo TEXT,
    analisis TEXT,                               -- JSON devuelto por la IA
    revisado_en TEXT
);
CREATE TABLE IF NOT EXISTS procesos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clave TEXT NOT NULL,
    ambito TEXT NOT NULL,
    organismo TEXT,
    puesto TEXT NOT NULL,
    subgrupo TEXT,
    datos TEXT NOT NULL,             -- JSON del proceso (temario, ejercicios, etc.)
    accesible TEXT NOT NULL,
    plazas INTEGER,
    fecha_publicacion TEXT,          -- primera vez que apareció
    fecha_boe TEXT,                  -- publicación en el BOE (si la hay)
    inicio_plazo TEXT,
    fin_plazo TEXT,
    plazo_texto TEXT,
    pendiente_extracto INTEGER DEFAULT 0,
    apertura_estimada TEXT,
    es_oep INTEGER DEFAULT 0,
    url_inscripcion TEXT,
    enlaces TEXT NOT NULL DEFAULT '[]',   -- [{"fuente","id","fecha","url","titulo"}]
    creado TEXT NOT NULL,
    actualizado TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_procesos_ambito ON procesos(ambito);
CREATE TABLE IF NOT EXISTS fechas_revisadas (
    fuente TEXT NOT NULL,
    fecha TEXT NOT NULL,
    resultado TEXT,
    PRIMARY KEY (fuente, fecha)
);
CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);
CREATE TABLE IF NOT EXISTS avisos (
    proceso_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,             -- nueva | abierta | cierra_pronto
    enviado TEXT NOT NULL,
    PRIMARY KEY (proceso_id, tipo)
);
"""


class DB:
    def __init__(self, ruta: Path | str):
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(ruta))
        self.con.row_factory = sqlite3.Row
        self.con.executescript(ESQUEMA)

    def cerrar(self):
        self.con.commit()
        self.con.close()

    def esta_vacia(self) -> bool:
        return self.con.execute("SELECT COUNT(*) FROM fechas_revisadas").fetchone()[0] == 0

    # --- meta -------------------------------------------------------------
    def meta(self, clave: str) -> str | None:
        fila = self.con.execute("SELECT valor FROM meta WHERE clave=?", (clave,)).fetchone()
        return fila["valor"] if fila else None

    def poner_meta(self, clave: str, valor: str):
        self.con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (clave, valor))
        self.con.commit()

    def olvidar_fechas_desde(self, desde: dt.date):
        """Para volver a revisar días pasados (p. ej. al añadir ayuntamientos)."""
        self.con.execute("DELETE FROM fechas_revisadas WHERE fecha >= ?", (desde.isoformat(),))
        self.con.commit()

    # --- fechas -----------------------------------------------------------
    def fecha_revisada(self, fuente: str, fecha: dt.date) -> bool:
        return self.con.execute("SELECT 1 FROM fechas_revisadas WHERE fuente=? AND fecha=?",
                                (fuente, fecha.isoformat())).fetchone() is not None

    def marcar_fecha(self, fuente: str, fecha: dt.date, resultado: str):
        self.con.execute("INSERT OR REPLACE INTO fechas_revisadas VALUES (?,?,?)",
                         (fuente, fecha.isoformat(), resultado))
        self.con.commit()

    # --- anuncios ---------------------------------------------------------
    def anuncio_conocido(self, ident: str) -> bool:
        fila = self.con.execute("SELECT estado FROM anuncios WHERE id=?", (ident,)).fetchone()
        return fila is not None and fila["estado"] in ("analizado", "descartado")

    def guardar_anuncio(self, a, estado: str, motivo: str = "", analisis: dict | None = None):
        self.con.execute(
            """INSERT INTO anuncios (id,fuente,fecha,titulo,organismo,ambito,url,estado,motivo,analisis,revisado_en)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET estado=excluded.estado, motivo=excluded.motivo,
                 analisis=excluded.analisis, revisado_en=excluded.revisado_en""",
            (a.id, a.fuente, a.fecha.isoformat(), a.titulo, a.organismo, a.ambito, a.url,
             estado, motivo, json.dumps(analisis, ensure_ascii=False) if analisis else None,
             dt.datetime.now().isoformat(timespec="seconds")))
        self.con.commit()

    # --- procesos ---------------------------------------------------------
    def procesos(self, ambito: str | None = None) -> list[sqlite3.Row]:
        if ambito:
            return self.con.execute("SELECT * FROM procesos WHERE ambito=?", (ambito,)).fetchall()
        return self.con.execute("SELECT * FROM procesos").fetchall()

    def proceso(self, pid: int) -> sqlite3.Row:
        return self.con.execute("SELECT * FROM procesos WHERE id=?", (pid,)).fetchone()

    def insertar_proceso(self, campos: dict) -> int:
        cols = ",".join(campos)
        marcas = ",".join("?" for _ in campos)
        cur = self.con.execute(f"INSERT INTO procesos ({cols}) VALUES ({marcas})",
                               list(campos.values()))
        self.con.commit()
        return cur.lastrowid

    def actualizar_proceso(self, pid: int, campos: dict):
        asignaciones = ",".join(f"{c}=?" for c in campos)
        self.con.execute(f"UPDATE procesos SET {asignaciones} WHERE id=?",
                         [*campos.values(), pid])
        self.con.commit()

    # --- avisos -----------------------------------------------------------
    def aviso_enviado(self, pid: int, tipo: str) -> bool:
        return self.con.execute("SELECT 1 FROM avisos WHERE proceso_id=? AND tipo=?",
                                (pid, tipo)).fetchone() is not None

    def marcar_aviso(self, pid: int, tipo: str):
        self.con.execute("INSERT OR IGNORE INTO avisos VALUES (?,?,?)",
                         (pid, tipo, dt.datetime.now().isoformat(timespec="seconds")))
        self.con.commit()
