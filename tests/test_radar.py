"""Pruebas sin conexión (python -m unittest discover -s tests)."""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from radar import config, filtros, ia, procesos, web  # noqa: E402
from radar.db import DB  # noqa: E402
from radar.fuentes import Anuncio, bocm, boe, bop_toledo, jccm  # noqa: E402
from radar.plazos import Calendario, domingo_de_pascua  # noqa: E402

FIX = RAIZ / "tests" / "fixtures"
CFG = config.cargar()


def leer(nombre: str) -> str:
    return (FIX / nombre).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
class TestFiltros(unittest.TestCase):
    def test_convocatorias(self):
        si = [
            "Resolución de 15 de octubre de 2026, por la que se convoca proceso selectivo para "
            "ingreso, por el sistema general de acceso libre, en el Cuerpo General Auxiliar.",
            "Resolución del Ayuntamiento de Alcorcón (Madrid), referente a la convocatoria para "
            "proveer varias plazas.",
            "– Alcorcón. Ofertas de empleo. Bases específicas proceso selectivo",
            "– Madrid. Personal. Oferta empleo público 2026",
            "Convocatoria por el sistema de acceso libre y promoción interna, Cuerpo Administrativo",
        ]
        no = [
            "Resolución por la que se convoca concurso general para la provisión de puestos de trabajo.",
            "Convoca proceso selectivo por el sistema de promoción interna en el Cuerpo Administrativo.",
            "Resolución por la que se aprueba la lista definitiva de admitidos y excluidos.",
            "– Alcorcón. Ofertas de empleo. Nombramiento funcionarios de carrera",
            "Orden por la que se convocan pruebas selectivas de ingreso al Cuerpo de Maestros.",
            "Resolución por la que se convocan subvenciones.",
        ]
        for t in si:
            self.assertTrue(filtros.parece_convocatoria(t), t)
        for t in no:
            self.assertFalse(filtros.parece_convocatoria(t), t)

    def test_titulos_reales_que_no_abren_plazo(self):
        # Vistos en la primera ejecución real (octubre de 2026)
        no = [
            "Aspirantes proceso selectivo — Resolución de 21 de septiembre de 2026, mediante la que se "
            "procede a la exclusión de aspirantes de las pruebas selectivas",
            "Resolución proceso selectivo – Resolución por la que se requiere documentación acreditativa",
            "Comisión permanente de selección – Resolución por la que se encomienda la realización del proceso selectivo",
            "Orden PJC/1040/2026, por la que se corrigen errores en la Orden PJC/999/2026",
            "Convocatoria proceso selectivo – Resolución por la que se procede a la ampliación del número de "
            "plazas correspondientes al proceso selectivo",
            "Resolución por la que se aprueba la relación definitiva de personas admitidas y excluidas, y se "
            "anuncia fecha y lugar de celebración del ejercicio único, del proceso selectivo",
        ]
        for t in no:
            self.assertFalse(filtros.parece_convocatoria(t), t)
        self.assertTrue(filtros.parece_convocatoria(
            "Convocatoria proceso selectivo – Orden 2056/2026, por la que se convocan pruebas selectivas "
            "para el ingreso, por el sistema general de acceso libre, en el Cuerpo de Técnicos"))

    def test_ambito_boe(self):
        self.assertEqual(filtros.ambito_boe("MINISTERIO DEL INTERIOR", "x", CFG), "estatal")
        self.assertEqual(filtros.ambito_boe(
            "ADMINISTRACIÓN LOCAL", "Resolución del Ayuntamiento de Alcorcón (Madrid)", CFG),
            "ayuntamiento_alcorcon")
        self.assertEqual(filtros.ambito_boe(
            "ADMINISTRACIÓN LOCAL", "Resolución del Ayuntamiento de Madrid, referente", CFG),
            "ayuntamiento_madrid")
        self.assertIsNone(filtros.ambito_boe(
            "ADMINISTRACIÓN LOCAL", "Resolución del Ayuntamiento de Madridejos (Toledo)", CFG))
        self.assertIsNone(filtros.ambito_boe("COMUNIDAD AUTÓNOMA DE ANDALUCÍA", "x", CFG))
        self.assertIsNone(filtros.ambito_boe("UNIVERSIDADES", "Universidad Rey Juan Carlos", CFG))

    def test_afin(self):
        self.assertTrue(filtros.es_afin("Técnico Auxiliar de Informática", CFG))
        self.assertFalse(filtros.es_afin("Auxiliar Administrativo", CFG))


# ---------------------------------------------------------------------------
class TestPlazos(unittest.TestCase):
    def test_pascua(self):
        self.assertEqual(domingo_de_pascua(2026), dt.date(2026, 4, 5))
        self.assertEqual(domingo_de_pascua(2027), dt.date(2027, 3, 28))

    def test_habiles_con_y_sin_traslado(self):
        pub = dt.date(2026, 10, 21)
        ini, fin = Calendario([dt.date(2026, 11, 2)]).fin_plazo(pub, 20, "habiles")
        self.assertEqual((ini, fin), (dt.date(2026, 10, 22), dt.date(2026, 11, 19)))
        _, fin2 = Calendario([]).fin_plazo(pub, 20, "habiles")
        self.assertEqual(fin2, dt.date(2026, 11, 18))

    def test_habiles_salta_festivos_nacionales(self):
        # Publicado el jueves 3 dic 2026: lunes 7 (traslado) y martes 8 son festivos
        _, fin = Calendario([dt.date(2026, 12, 7)]).fin_plazo(dt.date(2026, 12, 3), 3, "habiles")
        self.assertEqual(fin, dt.date(2026, 12, 10))

    def test_naturales_prorroga_si_acaba_en_inhabil(self):
        cal = Calendario()
        self.assertEqual(cal.fin_plazo(dt.date(2026, 10, 21), 20, "naturales")[1], dt.date(2026, 11, 10))
        self.assertEqual(cal.fin_plazo(dt.date(2026, 10, 19), 20, "naturales")[1], dt.date(2026, 11, 9))

    def test_meses(self):
        self.assertEqual(Calendario().fin_plazo(dt.date(2026, 1, 31), 1, "meses")[1], dt.date(2026, 3, 2))


# ---------------------------------------------------------------------------
class TestBOE(unittest.TestCase):
    def test_sumario(self):
        datos = json.loads(leer("boe_sumario.json"))
        anuncios = boe.anuncios_de_sumario(datos, dt.date(2026, 10, 21), CFG)
        ids = {a.id: a.ambito for a in anuncios}
        self.assertEqual(ids, {
            "BOE-A-2026-90001": "estatal",
            "BOE-A-2026-90010": "estatal",
            "BOE-A-2026-90040": "ayuntamiento_alcorcon",
            "BOE-A-2026-90042": "ayuntamiento_madrid",
        })
        a = next(x for x in anuncios if x.id == "BOE-A-2026-90010")
        self.assertIn("txt.php", a.url_texto)
        self.assertNotIn("/boe/dias/", a.url_texto)

    def test_texto_html(self):
        texto = boe.extraer_texto_html(leer("boe_txt.html"))
        self.assertIn("veinte días naturales", texto)
        self.assertNotIn("Menú del BOE", texto)


class TestBOCM(unittest.TestCase):
    def test_rss(self):
        bol = bocm.boletines_recientes(leer("bocm_rss.xml"))
        self.assertEqual(bol[-1], (dt.date(2026, 10, 21), 251))
        self.assertEqual(len(bol), 4)

    def test_sumario(self):
        entradas = bocm.entradas_sumario(leer("bocm_sumario.html"))
        por_cve = {e["cve"]: e for e in entradas}
        self.assertEqual(len(entradas), 11)
        self.assertEqual(por_cve["BOCM-20261021-1"]["seccion"], "autoridades_personal")
        self.assertIn("CONSEJERÍA DE PRESIDENCIA", por_cve["BOCM-20261021-1"]["organismo"])
        self.assertTrue(por_cve["BOCM-20261021-1"]["titulo"].startswith("Convocatoria proceso selectivo"))
        self.assertEqual(por_cve["BOCM-20261021-3"]["organismo"], "O. A. AGENCIA MADRILEÑA DE ATENCIÓN SOCIAL")
        self.assertEqual(por_cve["BOCM-20261021-5"]["seccion"], "otra")
        self.assertEqual(por_cve["BOCM-20261021-40"]["seccion"], "local")
        self.assertEqual(por_cve["BOCM-20261021-40"]["titulo"],
                         "– Alcorcón. Ofertas de empleo. Bases específicas proceso selectivo")
        anuncios = bocm.anuncios_de_sumario(leer("bocm_sumario.html"), dt.date(2026, 10, 21), CFG)
        self.assertEqual({a.id: a.ambito for a in anuncios}, {
            "BOCM-20261021-1": "comunidad_madrid",
            "BOCM-20261021-40": "ayuntamiento_alcorcon",
        })
        self.assertEqual(next(a for a in anuncios if a.ambito == "ayuntamiento_alcorcon").organismo,
                         "Ayuntamiento de Alcorcón")

    def test_cabecera_en_una_linea(self):
        html = ('<p>Sección: I. COMUNIDAD DE MADRID | B) Autoridades y Personal</p>'
                '<h4>CONSEJERÍA DE DIGITALIZACIÓN</h4><p>7</p><p>Convocatoria proceso selectivo</p>'
                '<p>– Orden por la que se convocan pruebas selectivas</p>'
                '<a href="/boletin/CM_Orden_BOCM/2026/10/21/BOCM-20261021-7.json">Json</a>')
        e = bocm.entradas_sumario(html)[0]
        self.assertEqual((e["seccion"], e["organismo"]), ("autoridades_personal", "CONSEJERÍA DE DIGITALIZACIÓN"))
        self.assertEqual(e["titulo"], "Convocatoria proceso selectivo – Orden por la que se convocan pruebas selectivas")

    def test_urls(self):
        self.assertEqual(bocm.url_json("BOCM-20261020-48"),
                         "https://www.bocm.es/boletin/CM_Orden_BOCM/2026/10/20/BOCM-20261020-48.json")
        self.assertTrue(bocm.url_pdf("BOCM-20261020-48").endswith("/BOCM-20261020-48.PDF"))


# ---------------------------------------------------------------------------
class TestEsquemaIA(unittest.TestCase):
    def test_esquema_compatible(self):
        prohibidas = {"minimum", "maximum", "minLength", "maxLength", "multipleOf"}

        def revisar(nodo, ruta="$"):
            if isinstance(nodo, dict):
                self.assertFalse(prohibidas & set(nodo), ruta)
                if nodo.get("type") == "object":
                    self.assertIs(nodo.get("additionalProperties"), False, ruta)
                    self.assertEqual(set(nodo["required"]), set(nodo["properties"]), ruta)
                for k, v in nodo.items():
                    revisar(v, f"{ruta}.{k}")
            elif isinstance(nodo, list):
                for i, v in enumerate(nodo):
                    revisar(v, f"{ruta}[{i}]")
        revisar(ia.ESQUEMA)

    def test_recorte_conserva_final(self):
        texto = "INICIO " + "x" * 1000 + " ANEXO TEMARIO"
        r = ia._recortar(texto, 200)
        self.assertTrue(r.startswith("INICIO") and r.endswith("ANEXO TEMARIO"))

    def test_modo_basico(self):
        a = Anuncio("BOE-A-1", "BOE", dt.date(2026, 10, 21), "Convocatoria auxiliar", "X", "estatal", "u")
        texto = ("Se convocan 120 plazas del Cuerpo General Auxiliar, Subgrupo C2. "
                 "El plazo de presentación será de veinte días hábiles contados a partir del día siguiente."
                 "\nTema 1. La Constitución.\nTema 2. La Corona.\nTema 25. Ofimática.")
        r = ia.analizar_basico(a, texto, CFG)
        p = r["procesos"][0]
        self.assertEqual((p["subgrupo"], p["accesible"], p["plazas_total"]), ("C2", "si", 120))
        self.assertEqual(p["temario"]["num_temas"], 25)
        self.assertEqual(r["plazo"], {"dias": 20, "tipo": "habiles", "cuenta_desde": "esta_publicacion",
                                      "fecha_fin_explicita": None})

    def test_llamada_api(self):
        respuesta = {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(
            {"tipo_publicacion": "convocatoria", "resumen": "r", "plazo": {}, "procesos": []})}]}
        a = Anuncio("BOE-A-1", "BOE", dt.date(2026, 10, 21), "t", "o", "estatal", "u")
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "clave-falsa"}), \
                mock.patch("radar.ia.requests.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = respuesta
            r = ia.analizar(a, "texto", CFG)
        cuerpo = post.call_args.kwargs["json"]
        self.assertEqual(cuerpo["model"], "claude-haiku-5-5")
        self.assertEqual(cuerpo["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(post.call_args.kwargs["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(r["_modo"], "ia")


# ---------------------------------------------------------------------------
def proceso_ia(puesto, subgrupo="C2", **extra):
    base = {
        "puesto": puesto, "cuerpo_escala": "", "subgrupo": subgrupo, "grupo_laboral_equivalente": None,
        "personal": "funcionario", "turno_libre": True, "plazas_libre": 2, "plazas_total": 2,
        "sistema": "oposicion", "titulacion_requerida": "ESO", "requisitos_extra": "",
        "accesible": "si", "motivo_accesible": "C2", "url_inscripcion": None, "tasa_euros": None,
        "temario": {"disponible": False, "num_temas": None, "bloques": []}, "ejercicios": [],
        "dificultad": {"nivel": 0, "explicacion": ""}, "aspirantes": {"estimacion": "", "explicacion": ""},
    }
    base.update(extra)
    return base


def analisis(tipo, procesos_, dias=20, tipo_dias="naturales", desde="esta_publicacion", apertura=None):
    return {"tipo_publicacion": tipo, "resumen": "", "referencia_bases": None,
            "apertura_estimada": apertura,
            "plazo": {"dias": dias, "tipo": tipo_dias, "cuenta_desde": desde, "fecha_fin_explicita": None},
            "procesos": procesos_}


class TestProcesos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = DB(Path(self.tmp.name) / "t.db")
        self.cal = Calendario(CFG.festivos_extra)

    def tearDown(self):
        self.db.cerrar()
        self.tmp.cleanup()

    def test_bases_bocm_y_extracto_boe_se_juntan(self):
        bases = Anuncio("BOCM-20261009-50", "BOCM", dt.date(2026, 10, 9), "– Alcorcón. Ofertas de empleo. Bases",
                        "Ayuntamiento de Alcorcón", "ayuntamiento_alcorcon", "https://www.bocm.es/bocm-20261009-50")
        temario = {"disponible": True, "num_temas": 20, "bloques": [{"nombre": "General", "num_temas": 20, "resumen": "x"}]}
        ev = procesos.registrar(self.db, CFG, self.cal, bases, analisis(
            "bases", [proceso_ia("Auxiliar Administrativo", temario=temario,
                                 dificultad={"nivel": 3, "explicacion": "media"}),
                      proceso_ia("Técnico de Administración General", "A1", accesible="no")],
            desde="extracto_boe", apertura="Cuando salga el extracto en el BOE"))
        self.assertEqual(len(ev), 1)  # el A1 no se guarda
        fila = self.db.proceso(ev[0][0])
        self.assertEqual(procesos.estado(fila, dt.date(2026, 10, 20)), "proxima")

        extracto = Anuncio("BOE-A-2026-90040", "BOE", dt.date(2026, 10, 21), "Resolución ... Alcorcón",
                           "ADMINISTRACIÓN LOCAL", "ayuntamiento_alcorcon", "https://www.boe.es/x")
        ev2 = procesos.registrar(self.db, CFG, self.cal, extracto,
                                 analisis("extracto", [proceso_ia("Auxiliar Administrativo/a")]))
        self.assertEqual(ev2, [(ev[0][0], "abierta")])
        fila = self.db.proceso(ev[0][0])
        self.assertEqual((fila["inicio_plazo"], fila["fin_plazo"], fila["fecha_boe"]),
                         ("2026-10-22", "2026-11-10", "2026-10-21"))
        self.assertEqual(procesos.estado(fila, dt.date(2026, 10, 25)), "abierta")
        self.assertEqual(procesos.estado(fila, dt.date(2026, 11, 11)), "cerrada")
        datos = json.loads(fila["datos"])
        self.assertEqual(datos["temario"]["num_temas"], 20)  # se conserva el temario de las bases
        self.assertEqual(len(json.loads(fila["enlaces"])), 2)
        self.assertEqual(fila["url_inscripcion"], "https://www.ayto-alcorcon.es/")

    def test_oep_y_convocatoria(self):
        oep = Anuncio("BOE-A-2026-90001", "BOE", dt.date(2026, 3, 1), "RD OEP", "MINISTERIO", "estatal", "u1")
        ev = procesos.registrar(self.db, CFG, self.cal, oep, analisis(
            "oferta_empleo_publico", [proceso_ia("Cuerpo General Auxiliar", cuerpo_escala="Cuerpo General Auxiliar de la Administración del Estado"),
                                      proceso_ia("Cuerpo General Administrativo", "C1")],
            dias=None, tipo_dias="desconocido", desde="no_aplica", apertura="6-12 meses"))
        self.assertEqual(len(ev), 2)
        self.assertEqual(procesos.estado(self.db.proceso(ev[0][0]), dt.date(2026, 5, 1)), "prevista")

        conv = Anuncio("BOE-A-2026-90010", "BOE", dt.date(2026, 10, 21), "convoca auxiliar", "MINISTERIO", "estatal", "u2")
        ev2 = procesos.registrar(self.db, CFG, self.cal, conv, analisis(
            "convocatoria", [proceso_ia("Cuerpo General Auxiliar de la Administración del Estado")],
            tipo_dias="habiles"))
        self.assertEqual(ev2, [(ev[0][0], "abierta")])
        fila = self.db.proceso(ev[0][0])
        self.assertEqual(fila["fin_plazo"], "2026-11-19")
        self.assertEqual(fila["url_inscripcion"], "https://administracion.gob.es/PAG/ips")
        # el C1 sigue como previsto, no se mezcla con el C2
        self.assertEqual(procesos.estado(self.db.proceso(ev[1][0]), dt.date(2026, 10, 25)), "prevista")

    def test_reprocesar_no_duplica(self):
        a = Anuncio("BOE-A-2026-1", "BOE", dt.date(2026, 10, 21), "t", "M", "estatal", "u")
        an = analisis("convocatoria", [proceso_ia("Auxiliar de Biblioteca")])
        procesos.registrar(self.db, CFG, self.cal, a, an)
        procesos.registrar(self.db, CFG, self.cal, a, an)
        self.assertEqual(len(self.db.procesos()), 1)

    def test_nueva_edicion_tras_cierre(self):
        a1 = Anuncio("BOE-A-2025-1", "BOE", dt.date(2025, 10, 1), "t", "M", "estatal", "u")
        a2 = Anuncio("BOE-A-2026-1", "BOE", dt.date(2026, 10, 1), "t", "M", "estatal", "u")
        an = analisis("convocatoria", [proceso_ia("Auxiliar de Biblioteca")])
        procesos.registrar(self.db, CFG, self.cal, a1, an)
        procesos.registrar(self.db, CFG, self.cal, a2, an)
        self.assertEqual(len(self.db.procesos()), 2)

    def test_mensaje_telegram(self):
        from radar import telegram
        a = Anuncio("BOE-A-2026-7", "BOE", dt.date(2026, 10, 21), "t", "MINISTERIO", "estatal",
                    "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-7")
        ev = procesos.registrar(self.db, CFG, self.cal, a, analisis("convocatoria", [proceso_ia(
            "Auxiliar <Administrativo>", dificultad={"nivel": 4, "explicacion": "x"},
            temario={"disponible": True, "num_temas": 28, "bloques": []})], tipo_dias="habiles"))
        texto = telegram.mensaje(self.db.proceso(ev[0][0]), CFG, "nueva", dt.date(2026, 10, 23))
        self.assertIn("Auxiliar &lt;Administrativo&gt;", texto)
        self.assertIn("abierta hasta el <b>19/11/2026</b>", texto)
        self.assertIn("28 temas", texto)
        self.assertIn("★★★★☆", texto)
        self.assertIn('href="https://administracion.gob.es/PAG/ips">Inscribirme', texto)

    def test_exportar_web(self):
        a = Anuncio("BOE-A-2026-1", "BOE", dt.date(2026, 10, 21), "t", "MINISTERIO", "estatal", "u")
        procesos.registrar(self.db, CFG, self.cal, a, analisis("convocatoria", [proceso_ia("Auxiliar de Informática", "C1")]))
        ruta = Path(self.tmp.name) / "data.js"
        n = web.exportar(self.db, CFG, dt.date(2026, 10, 22), ruta)
        self.assertEqual(n, 1)
        contenido = ruta.read_text(encoding="utf-8")
        datos = json.loads(re.sub(r"^window\.RADAR = |;\s*$", "", contenido))
        o = datos["oposiciones"][0]
        self.assertEqual((o["estado"], o["afin"], o["ambitoNombre"]), ("abierta", True, "Estado (AGE)"))


# ---------------------------------------------------------------------------
class RespuestaFalsa:
    def __init__(self, texto="", datos=None, contenido=b"", status=200):
        self.text, self._datos, self.content, self.status_code = texto, datos, contenido, status
        self.encoding = "utf-8"

    def json(self):
        return self._datos if self._datos is not None else json.loads(self.text)


class ClienteFalso:
    """Simula BOE y BOCM con las páginas de prueba."""
    def __init__(self, *a, **k):
        self.pedidas = []

    def get(self, url, accept=None, permitir_404=False, **k):
        self.pedidas.append(url)
        if "datosabiertos/api/boe/sumario/20261021" in url:
            return RespuestaFalsa(leer("boe_sumario.json"))
        if "datosabiertos/api/boe/sumario/" in url:
            return None  # otros días: sin BOE
        if "txt.php" in url:
            return RespuestaFalsa(leer("boe_txt.html"))
        if url.endswith("sumarios.rss"):
            return RespuestaFalsa(leer("bocm_rss.xml"))
        if "/print/boletin-completo/BOCM-20261021/251" in url:
            return RespuestaFalsa(leer("bocm_sumario.html"))
        if "/print/boletin-completo/" in url:
            return RespuestaFalsa("<html><body>Sin anuncios</body></html>")
        if url.endswith(".json"):
            return RespuestaFalsa(datos={"text": "Bases. Subgrupo C2. Auxiliar administrativo. " * 200})
        raise AssertionError("URL inesperada " + url)


def analisis_falso(anuncio, texto, cfg):
    if "OEP" in anuncio.titulo or "oferta de empleo" in anuncio.titulo.lower():
        return analisis("oferta_empleo_publico", [proceso_ia("Cuerpo de Gestión Penitenciaria", "A2", accesible="no"),
                                                   proceso_ia("Ayudantes de Instituciones Penitenciarias", "C1")],
                        dias=None, tipo_dias="desconocido", desde="no_aplica", apertura="2027")
    if anuncio.id == "BOCM-20261021-40":
        return analisis("bases", [proceso_ia("Auxiliar Administrativo")], desde="extracto_boe")
    if anuncio.fuente == "BOE" and anuncio.ambito == "ayuntamiento_alcorcon":
        return analisis("extracto", [proceso_ia("Auxiliar Administrativo")])
    return analisis("convocatoria", [proceso_ia(f"Plaza {anuncio.id}")], tipo_dias="habiles")


class TestIntegracion(unittest.TestCase):
    def test_ejecucion_completa(self):
        from radar import main as principal

        with tempfile.TemporaryDirectory() as tmp:
            ruta_db, ruta_web = Path(tmp) / "radar.db", Path(tmp) / "docs"
            enviados = []
            with mock.patch.object(principal, "RUTA_DB", ruta_db), \
                    mock.patch.object(principal, "RUTA_WEB", ruta_web), \
                    mock.patch.object(principal, "Cliente", ClienteFalso), \
                    mock.patch.object(principal, "hoy_madrid", lambda: dt.date(2026, 10, 21)), \
                    mock.patch.object(principal.ia, "analizar", analisis_falso), \
                    mock.patch.object(principal.telegram, "enviar", lambda cfg, t: enviados.append(t) or True):
                self.assertEqual(principal.main(["--dias", "3"]), 0)
                # primera vez: un único mensaje de resumen
                self.assertEqual(len(enviados), 1)
                self.assertIn("Radar de oposiciones activado", enviados[0])

                db = DB(ruta_db)
                filas = db.procesos()
                puestos = sorted(f["puesto"] for f in filas)
                self.assertIn("Auxiliar Administrativo", puestos)
                self.assertNotIn("Cuerpo de Gestión Penitenciaria", puestos)
                alcorcon = [f for f in filas if f["ambito"] == "ayuntamiento_alcorcon"]
                self.assertEqual(len(alcorcon), 1)  # bases BOCM + extracto BOE = 1 oposición
                self.assertEqual(procesos.estado(alcorcon[0], dt.date(2026, 10, 21)), "proxima")
                self.assertTrue(db.fecha_revisada("BOE", dt.date(2026, 10, 21)))
                self.assertTrue(db.fecha_revisada("BOE", dt.date(2026, 10, 19)))
                self.assertFalse(db.anuncio_conocido("BOE-A-2026-90011"))
                db.cerrar()

                # segunda ejecución: no repite descargas de anuncios ya vistos ni avisos
                enviados.clear()
                self.assertEqual(principal.main(["--dias", "3"]), 0)
                self.assertEqual(enviados, [])

            datos = (ruta_web / "data.js").read_text(encoding="utf-8")
            self.assertIn("Auxiliar Administrativo", datos)

    def test_extracto_trae_las_bases_del_bocm(self):
        from radar import main as principal

        html_bases = ('<h3>Sección: <strong>III. ADMINISTRACIÓN LOCAL AYUNTAMIENTOS</strong></h3>'
                      '<div>50</div><div>– Alcorcón. Ofertas de empleo. Bases proceso selectivo</div>'
                      '<a href="https://www.bocm.es/boletin/CM_Orden_BOCM/2026/10/09/BOCM-20261009-50.json">Json</a>')

        class Cliente2(ClienteFalso):
            def get(self, url, **k):
                if "/print/boletin-completo/BOCM-20261009/240" in url:
                    self.pedidas.append(url)
                    return RespuestaFalsa(html_bases)
                return super().get(url, **k)

        temario = {"disponible": True, "num_temas": 18, "bloques": [{"nombre": "B", "num_temas": 18, "resumen": "r"}]}

        def analizar(anuncio, texto, cfg):
            if anuncio.id == "BOE-A-2026-90040":
                r = analisis("extracto", [proceso_ia("Auxiliar Administrativo")])
                r["bases_bocm"] = {"numero": 240, "fecha": "2026-10-09"}
                return r
            if anuncio.id == "BOCM-20261009-50":
                return analisis("bases", [proceso_ia("Auxiliar Administrativo", temario=temario)],
                                desde="extracto_boe")
            return analisis("otro", [])

        a = Anuncio("BOE-A-2026-90040", "BOE", dt.date(2026, 10, 21), "Resolución Alcorcón",
                    "ADMINISTRACIÓN LOCAL", "ayuntamiento_alcorcon",
                    "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-90040",
                    url_texto="https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-90040")
        with tempfile.TemporaryDirectory() as tmp:
            db = DB(Path(tmp) / "t.db")
            with mock.patch.object(principal.ia, "analizar", analizar):
                eventos, fallidas = principal.procesar([a], Cliente2(), CFG, db, Calendario())
            self.assertEqual(fallidas, set())
            filas = db.procesos()
            self.assertEqual(len(filas), 1)
            self.assertEqual(json.loads(filas[0]["datos"])["temario"]["num_temas"], 18)
            self.assertEqual(filas[0]["inicio_plazo"], "2026-10-22")
            self.assertEqual([e["id"] for e in json.loads(filas[0]["enlaces"])],
                             ["BOCM-20261009-50", "BOE-A-2026-90040"])
            db.cerrar()


# ---------------------------------------------------------------------------
class TestFuentesNuevas(unittest.TestCase):
    def test_ambitos_nuevos(self):
        self.assertEqual(filtros.ambito_boe("COMUNIDAD AUTÓNOMA DE CASTILLA-LA MANCHA", "x", CFG),
                         "castilla_la_mancha")
        self.assertEqual(filtros.ambito_boe(
            "ADMINISTRACIÓN LOCAL", "Resolución del Ayuntamiento de Seseña (Toledo), referente", CFG),
            "ayuntamiento_sesena")
        self.assertEqual(filtros.ambito_boe(
            "ADMINISTRACIÓN LOCAL", "Resolución del Ayuntamiento de Aranjuez (Madrid)", CFG),
            "ayuntamiento_aranjuez")
        self.assertEqual(filtros.ambito_bocm("local", "– Valdemoro. Ofertas de empleo. Bases", "", CFG),
                         "ayuntamiento_valdemoro")
        self.assertEqual(filtros.ambito_bocm("local", "– Pinto. Personal. Bases proceso selectivo", "", CFG),
                         "ayuntamiento_pinto")
        self.assertIsNone(filtros.ambito_bocm("local", "– Pinto. Urbanismo. Plan", "", CFG))
        self.assertEqual(CFG.region("ayuntamiento_sesena"), "clm")
        self.assertEqual(CFG.nombre_ambito("castilla_la_mancha"), "Castilla-La Mancha")

    def test_festivos_por_region(self):
        mad, clm = Calendario(region="madrid"), Calendario(region="clm")
        self.assertTrue(mad.es_inhabil(dt.date(2028, 5, 2)))   # martes, Día de la Comunidad de Madrid
        self.assertFalse(clm.es_inhabil(dt.date(2028, 5, 2)))
        self.assertTrue(clm.es_inhabil(dt.date(2028, 5, 31)))  # miércoles, Día de Castilla-La Mancha
        self.assertFalse(mad.es_inhabil(dt.date(2028, 5, 31)))

    def test_jccm_listado(self):
        procs = jccm.procesos_de_listado(leer("jccm_listado.html"))
        self.assertEqual(len(procs), 4)
        self.assertEqual([jccm.accesible_por_titulo(u.split("/")[-1].replace("-", " ")) for u, _ in procs],
                         [True, False, True, True])

    def test_jccm_pagina(self):
        url = "https://empleopublico.castillalamancha.es/procesos-selectivos/abiertos/turno-libre/2026-cuerpo-auxiliar-auxiliar-turno-libre"
        p = jccm.pagina_proceso(leer("jccm_proceso.html"), url)
        self.assertEqual(p["titulo"], "2026 - Cuerpo AUXILIAR - Auxiliar - Turno Libre")
        self.assertIn("180", p["texto"])
        conv = jccm.documento_convocatoria(p["documentos"])
        self.assertEqual((conv["fecha"], conv["url"].rsplit("/", 1)[-1]),
                         (dt.date(2026, 10, 15), "convocatoria_libre_funcionarios.pdf"))
        self.assertTrue(jccm.documento_temario(p["documentos"])["url"].endswith("c2_cuerpo_auxiliar.pdf"))

    def test_jccm_obtener(self):
        class C:
            pedidas = []
            def get(self, url, **k):
                self.pedidas.append(url)
                if url.endswith("/turno-libre"):
                    return RespuestaFalsa(leer("jccm_listado.html"))
                if "2026-cuerpo-auxiliar" in url:
                    return RespuestaFalsa(leer("jccm_proceso.html"))
                if "/turno-libre/" in url:
                    return RespuestaFalsa("<main><h1>Otro</h1><div>18/12/2024 <a href='/c.pdf'>Convocatoria</a></div></main>")
                return RespuestaFalsa("<html></html>")
        c = C()
        lista = jccm.obtener_anuncios(c, CFG, lambda i: False, dt.date(2026, 10, 22))
        por_id = {a.id: a for a in lista}
        self.assertNotIn("JCCM-2026-cuerpo-superior-juridica-turno-libre", por_id)  # A1: ni se descarga
        self.assertFalse(any("juridica" in u for u in c.pedidas))
        aux = por_id["JCCM-2026-cuerpo-auxiliar-auxiliar-turno-libre"]
        self.assertEqual((aux.fecha, aux.extra["antigua"], aux.ambito), (dt.date(2026, 10, 15), False, "castilla_la_mancha"))
        self.assertTrue(por_id["JCCM-2023-2024-cuerpo-ejecutivo-administrativos-turno-libre"].extra["antigua"])

    def test_bop_toledo(self):
        lista = bop_toledo.entradas_resumen(leer("bop_resumen.html"), CFG, dt.date(2026, 10, 21))
        self.assertEqual([(a.id, a.ambito) for a in lista], [("BOPTO-2026-4801", "ayuntamiento_sesena")])
        self.assertIn("insert_number=4801", lista[0].url_pdf)
        self.assertTrue(bop_toledo.url_resumen(dt.date(2026, 10, 21)).endswith(
            "publication_date=21/10/2026&publication_date_to=21/10/2026"))

    def test_bop_bloqueado_por_robots_no_rompe(self):
        from radar import main as principal
        from radar.http import BloqueadoPorRobots

        class C(ClienteFalso):
            def get(self, url, **k):
                if "diputoledo" in url:
                    raise BloqueadoPorRobots(url)
                if "castillalamancha" in url:
                    return RespuestaFalsa("<html></html>")
                return super().get(url, **k)
        with tempfile.TemporaryDirectory() as tmp:
            db = DB(Path(tmp) / "t.db")
            est = principal.Estado()
            anuncios, revisadas, errores = principal.recoger_anuncios(
                C(), CFG, db, [dt.date(2026, 10, 21)], dt.date(2026, 10, 21), est)
            self.assertTrue(est.fuentes["BOP Toledo"].get("robots"))
            self.assertTrue(est.alguna_ok())
            self.assertIn(("BOE", dt.date(2026, 10, 21)), revisadas)
            db.cerrar()

    def test_ambitos_nuevos_reescanean_y_resumen(self):
        from radar import main as principal

        class C(ClienteFalso):
            def get(self, url, **k):
                if "diputoledo" in url or "castillalamancha" in url:
                    return RespuestaFalsa("<html></html>")
                return super().get(url, **k)

        with tempfile.TemporaryDirectory() as tmp:
            ruta_db = Path(tmp) / "radar.db"
            db = DB(ruta_db)
            db.marcar_fecha("BOE", dt.date(2026, 10, 21), "0 candidatos")  # BD de la versión anterior
            db.marcar_fecha("BOCM", dt.date(2026, 10, 21), "0 candidatos")
            db.cerrar()
            enviados = []
            with mock.patch.object(principal, "RUTA_DB", ruta_db), \
                    mock.patch.object(principal, "RUTA_WEB", Path(tmp) / "docs"), \
                    mock.patch.object(principal, "Cliente", C), \
                    mock.patch.object(principal, "hoy_madrid", lambda: dt.date(2026, 10, 21)), \
                    mock.patch.object(principal.ia, "analizar", analisis_falso), \
                    mock.patch.object(principal.telegram, "enviar", lambda cfg, t: enviados.append(t) or True):
                principal.main(["--dias", "1"])
            self.assertEqual(len(enviados), 1)
            self.assertIn("Radar ampliado", enviados[0])
            self.assertIn("Aranjuez", enviados[0])
            db = DB(ruta_db)
            self.assertGreater(len(db.procesos()), 0)  # el 21/10 se volvió a revisar
            self.assertIn("ayuntamiento_sesena", json.loads(db.meta("ambitos")))
            db.cerrar()
            self.assertTrue((Path(tmp) / "estado.json").exists())


if __name__ == "__main__":
    unittest.main()
