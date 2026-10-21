"""Cliente HTTP educado: respeta robots.txt, espera entre peticiones y reintenta."""
from __future__ import annotations

import logging
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

USER_AGENT = "RadarOposiciones/1.0 (uso personal; una consulta diaria de convocatorias)"


class BloqueadoPorRobots(Exception):
    """La URL está excluida por el robots.txt del sitio."""


class Cliente:
    def __init__(self, pausas: dict[str, float] | None = None, timeout: int = 40):
        self.sesion = requests.Session()
        self.sesion.headers["User-Agent"] = USER_AGENT
        self.timeout = timeout
        self.pausas = pausas or {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._ultima: dict[str, float] = {}

    # ---------------------------------------------------------------
    def _robots_de(self, host: str):
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.sesion.get(f"https://{host}/robots.txt", timeout=self.timeout)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                else:
                    rp = None  # sin robots.txt: todo permitido
            except requests.RequestException as e:
                log.warning("No se pudo leer robots.txt de %s: %s", host, e)
                rp = None
            self._robots[host] = rp
        return self._robots[host]

    def permitido(self, url: str) -> bool:
        rp = self._robots_de(urlparse(url).netloc)
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    def _esperar(self, host: str):
        pausa = self.pausas.get(host, 1.0)
        rp = self._robots.get(host)
        if rp is not None:
            delay = rp.crawl_delay(USER_AGENT)
            if delay:
                pausa = max(pausa, float(delay))
        transcurrido = time.monotonic() - self._ultima.get(host, 0)
        if transcurrido < pausa:
            time.sleep(pausa - transcurrido)
        self._ultima[host] = time.monotonic()

    # ---------------------------------------------------------------
    def get(self, url: str, *, accept: str | None = None, intentos: int = 3,
            permitir_404: bool = False) -> requests.Response | None:
        host = urlparse(url).netloc
        if not self.permitido(url):
            raise BloqueadoPorRobots(url)
        headers = {"Accept": accept} if accept else {}
        for intento in range(1, intentos + 1):
            self._esperar(host)
            try:
                r = self.sesion.get(url, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                log.warning("Error de red en %s (intento %d): %s", url, intento, e)
            else:
                if r.status_code == 404 and permitir_404:
                    return None
                if r.status_code < 500 and r.status_code != 429:
                    r.raise_for_status()
                    return r
                log.warning("HTTP %s en %s (intento %d)", r.status_code, url, intento)
            time.sleep(5 * intento)
        raise requests.HTTPError(f"No se pudo descargar {url}")
