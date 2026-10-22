"""Cálculo de plazos de inscripción (Ley 39/2015, art. 30).

- Días hábiles: se excluyen sábados, domingos y festivos.
- Días naturales: se cuentan todos, pero si el último día es inhábil el plazo
  se prorroga al primer día hábil siguiente.
- Meses: de fecha a fecha; si no existe ese día en el mes final, el último día
  del mes; y si es inhábil, el siguiente hábil.
El cómputo empieza el día siguiente a la publicación.

Los festivos locales de cada municipio no se incluyen, así que la fecha final
es una estimación muy fiable pero conviene confirmarla en la convocatoria.
"""
from __future__ import annotations

import calendar
import datetime as dt
from functools import lru_cache

_FIJOS = [(1, 1), (1, 6), (5, 1), (8, 15), (10, 12), (11, 1), (12, 6), (12, 8), (12, 25)]
# Día de la comunidad autónoma (los traslados de cada año van en festivos_extra)
_REGIONALES = {"madrid": [(5, 2)], "clm": [(5, 31)], "estado": [(5, 2)]}


def domingo_de_pascua(anio: int) -> dt.date:
    """Algoritmo de Meeus/Jones/Butcher (calendario gregoriano)."""
    a = anio % 19
    b, c = divmod(anio, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return dt.date(anio, mes, dia)


@lru_cache(maxsize=None)
def _festivos_base(anio: int, region: str = "madrid") -> frozenset[dt.date]:
    pascua = domingo_de_pascua(anio)
    dias = {dt.date(anio, m, d) for m, d in _FIJOS + _REGIONALES.get(region, [])}
    dias.add(pascua - dt.timedelta(days=3))  # Jueves Santo (Madrid y Castilla-La Mancha)
    dias.add(pascua - dt.timedelta(days=2))  # Viernes Santo
    return frozenset(dias)


class Calendario:
    def __init__(self, festivos_extra: list[dt.date] | None = None, region: str = "madrid"):
        self.extra = set(festivos_extra or [])
        self.region = region

    def para(self, region: str) -> "Calendario":
        """Mismo calendario con los festivos de otra comunidad autónoma."""
        return self if region == self.region else Calendario(list(self.extra), region)

    def es_inhabil(self, d: dt.date) -> bool:
        return d.weekday() >= 5 or d in _festivos_base(d.year, self.region) or d in self.extra

    def siguiente_habil(self, d: dt.date) -> dt.date:
        while self.es_inhabil(d):
            d += dt.timedelta(days=1)
        return d

    def fin_plazo(self, publicacion: dt.date, dias: int, tipo: str) -> tuple[dt.date, dt.date]:
        """Devuelve (inicio, fin) del plazo contado desde el día siguiente a `publicacion`."""
        inicio = publicacion + dt.timedelta(days=1)
        if tipo == "habiles":
            inicio = self.siguiente_habil(inicio)
            d, contados = inicio, 1
            while contados < dias:
                d += dt.timedelta(days=1)
                if not self.es_inhabil(d):
                    contados += 1
            return inicio, d
        if tipo == "meses":
            m = publicacion.month - 1 + dias
            anio, mes = publicacion.year + m // 12, m % 12 + 1
            ultimo = calendar.monthrange(anio, mes)[1]
            fin = dt.date(anio, mes, min(publicacion.day, ultimo))
            return inicio, self.siguiente_habil(fin)
        # naturales (y por defecto)
        fin = publicacion + dt.timedelta(days=dias)
        return inicio, self.siguiente_habil(fin)
