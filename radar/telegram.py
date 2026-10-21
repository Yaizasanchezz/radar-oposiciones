"""Avisos por Telegram (Bot API)."""
from __future__ import annotations

import datetime as dt
import html
import json
import logging

import requests

from .config import Config
from .procesos import estado

log = logging.getLogger(__name__)


def enviar(cfg: Config, texto: str) -> bool:
    if not (cfg.telegram_token and cfg.telegram_chat_id):
        log.info("Telegram sin configurar; aviso no enviado:\n%s", texto)
        return False
    r = requests.post(
        f"https://api.telegram.org/bot{cfg.telegram_token}/sendMessage",
        json={"chat_id": cfg.telegram_chat_id, "text": texto[:4000], "parse_mode": "HTML",
              "disable_web_page_preview": True},
        timeout=30,
    )
    if r.status_code != 200:
        log.error("Telegram respondió %s: %s", r.status_code, r.text[:200])
        return False
    return True


def _f(s: str | None) -> str:
    return dt.date.fromisoformat(s).strftime("%d/%m/%Y") if s else ""


def mensaje(fila, cfg: Config, tipo: str, hoy: dt.date) -> str:
    datos = json.loads(fila["datos"])
    e = html.escape
    titulos = {
        "nueva": "🌸 <b>Nueva oposición</b>",
        "abierta": "🔓 <b>¡Ya se puede pedir!</b>",
        "cierra_pronto": "⏰ <b>Cierra pronto</b>",
    }
    lineas = [titulos[tipo], f"<b>{e(fila['puesto'])}</b> · {e(fila['subgrupo'] or '')}",
              e(cfg.nombre_ambito(fila["ambito"]))]
    if fila["plazas"]:
        lineas.append(f"Plazas: {fila['plazas']}")
    est = estado(fila, hoy)
    if est == "abierta" and fila["fin_plazo"]:
        lineas.append(f"Inscripción abierta hasta el <b>{_f(fila['fin_plazo'])}</b> (estimado)")
    elif est == "abierta":
        lineas.append("Inscripción abierta (fecha de fin por confirmar)")
    elif est == "proxima" and fila["inicio_plazo"]:
        lineas.append(f"Abre el {_f(fila['inicio_plazo'])}")
    elif est in ("proxima", "prevista") and fila["apertura_estimada"]:
        lineas.append(f"Apertura: {e(fila['apertura_estimada'])}")
    temario = datos.get("temario") or {}
    if temario.get("num_temas"):
        lineas.append(f"Temario: {temario['num_temas']} temas")
    if (datos.get("dificultad") or {}).get("nivel"):
        n = datos["dificultad"]["nivel"]
        lineas.append("Dificultad: " + "★" * n + "☆" * (5 - n))
    if fila["accesible"] == "dudoso":
        lineas.append(f"⚠️ Revisa requisitos: {e(datos.get('motivo_accesible', ''))}")
    enlaces = []
    if est == "abierta" and fila["url_inscripcion"]:
        enlaces.append(f'<a href="{e(fila["url_inscripcion"])}">Inscribirme</a>')
    ult = json.loads(fila["enlaces"])[-1]
    enlaces.append(f'<a href="{e(ult["url"])}">{e(ult["fuente"])}</a>')
    if cfg.url_web:
        enlaces.append(f'<a href="{e(cfg.url_web)}">Ver en la web</a>')
    lineas.append(" · ".join(enlaces))
    return "\n".join(lineas)
