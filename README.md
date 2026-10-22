# 🌸 Radar de oposiciones

Vigila cada mañana el **BOE**, el **BOCM**, el **portal de empleo público de Castilla-La Mancha**
y el **BOP de Toledo**, encuentra las oposiciones a las que puedes
presentarte con un **Técnico Superior** (subgrupos **C1, C2** y **Agrupaciones Profesionales**,
y sus equivalentes laborales), las guarda en una pequeña base de datos, publica una web
sencilla en tonos rosas y te avisa por **Telegram** cuando sale algo nuevo.

Ámbitos incluidos:
- **Estado** (BOE)
- **Comunidad de Madrid** (BOCM + BOE)
- **Junta de Castilla-La Mancha** (portal de empleo público de la Junta + BOE)
- **Ayuntamientos de Madrid:** Madrid, Alcorcón, Aranjuez, Ciempozuelos, Valdemoro y Pinto (bases en el BOCM, plazo con el extracto del BOE)
- **Ayuntamientos de Toledo:** Seseña e Illescas (bases en el BOP de Toledo, plazo con el extracto del BOE)

Añadir más es copiar tres líneas en `config.yaml`.

## Qué te enseña de cada oposición

| | |
|---|---|
| Estado | **Abierta** (hasta qué día y cuántos días quedan) · **Próxima** (bases publicadas, falta el extracto del BOE) · **Prevista** (en la Oferta de Empleo Público, aún sin convocar, con fecha estimada) · **Cerrada** |
| Fechas | Cuándo salió en el BOE / BOCM, inicio y fin del plazo calculados (días hábiles o naturales, festivos incluidos) |
| Inscripción | Botón **Inscribirme** a la plataforma oficial (IPS del Estado, Comunidad de Madrid o sede del ayuntamiento) cuando el plazo está abierto |
| Temario | Nº de temas y un resumen de cada bloque |
| Ejercicios | Cada prueba: tipo, nº de preguntas, si es eliminatoria, pruebas físicas… |
| Estimaciones | Dificultad (1–5 ★) y aspirantes esperados, con su explicación |
| Extras | Plazas, sistema (oposición / concurso-oposición), tasa, requisitos, etiqueta **Afín a ti** (informática, marketing…) y aviso si un requisito es dudoso |

Avisos de Telegram: oposición nueva, cuando una "próxima" abre plazo y un recordatorio 3 días
antes del cierre. La primera vez solo manda un resumen (no 40 mensajes seguidos).

## Cómo funciona

```
GitHub Actions (cada día 06:47 UTC)
  ├─ BOE: API oficial de datos abiertos → sección II.B + Ofertas de Empleo Público
  ├─ BOCM: sumario diario → Comunidad de Madrid (Autoridades y personal) + tus ayuntamientos
  ├─ Portal de empleo público de la Junta de CLM → procesos C1/C2/laboral III-V recién convocados
  ├─ BOP de Toledo (si su robots.txt lo permite) → bases de Seseña e Illescas
  ├─ Filtros rápidos (descarta traslados, libre designación, listas de admitidos, docentes…)
  ├─ Claude (IA) lee cada convocatoria y devuelve un JSON: grupo, plazas, plazo, temario…
  ├─ SQLite (data/radar.db): junta OEP + bases + extracto en una sola oposición, sin repetir
  ├─ Telegram: avisos
  └─ docs/data.js → la web (GitHub Pages) se actualiza sola
```

Un detalle importante de los ayuntamientos: las **bases** salen primero en el BOCM, pero el
**plazo se abre con el extracto en el BOE**. El radar guarda la oposición como "Próxima" al ver
las bases y la pasa a "Abierta" (y te avisa) cuando sale el extracto. Si el extracto del BOE
llega primero, busca automáticamente las bases en el BOCM para sacar el temario.

---

## Puesta en marcha (unos 20 minutos)

Necesitas: una cuenta de GitHub (gratis), Telegram y, recomendado, una clave de la API de
Claude (el coste son céntimos al mes; sin ella funciona en modo básico, sin resúmenes de
temario ni estimaciones).

### 1. Sube el proyecto a GitHub

Crea un repositorio **público** vacío (p. ej. `radar-oposiciones`) y desde esta carpeta:

```bash
git init -b main
git add .
git commit -m "Radar de oposiciones"
git remote add origin https://github.com/TU_USUARIO/radar-oposiciones.git
git push -u origin main
```

> Público porque GitHub Pages es gratis en repos públicos. Los datos son de boletines oficiales
> y tus claves van como secretos (nadie las ve). La web lleva `noindex` para que no salga en Google.

### 2. Crea tu bot de Telegram

1. En Telegram, habla con **@BotFather** → `/newbot` → ponle nombre. Te dará un **token**.
2. Escribe "hola" a tu bot nuevo.
3. En tu ordenador: `pip install requests` y `python scripts/telegram_chat_id.py TU_TOKEN`.
   Te dirá tu **chat_id** y te mandará un mensaje de prueba.

### 3. Consigue la clave de Claude (opcional, recomendado)

En [platform.claude.com](https://platform.claude.com/) → *API keys* → crea una clave y añade un
poco de saldo. Se usa `claude-haiku-5-5`, el modelo más barato: leer una convocatoria cuesta
fracciones de céntimo.

### 4. Guarda los secretos en GitHub

Repositorio → **Settings → Secrets and variables → Actions → New repository secret**:

| Nombre | Valor |
|---|---|
| `TELEGRAM_BOT_TOKEN` | el token de BotFather |
| `TELEGRAM_CHAT_ID` | el número que te dio el script |
| `ANTHROPIC_API_KEY` | tu clave de Claude |

### 5. Activa la web

**Settings → Pages → Build and deployment**: *Deploy from a branch* → rama `main`, carpeta
`/docs` → Save. Tu web será `https://TU_USUARIO.github.io/radar-oposiciones/`.

### 6. Primera ejecución

Pestaña **Actions** → *Radar diario de oposiciones* → **Run workflow**. La primera vez revisa
las últimas 3 semanas y tarda bastante (el BOCM pide 10 s entre peticiones y la IA lee cada
convocatoria): entre 15 y 60 minutos. Después, cada día tarda unos minutos.

Si el paso "Guardar cambios" falla con un error de permisos: **Settings → Actions → General →
Workflow permissions → Read and write permissions**.

---

## Personalizar (`config.yaml`)

- **Más ayuntamientos**: copia el bloque de Alcorcón y cambia nombre, clave y web.
- **Universidades públicas de Madrid** (plazas C1/C2 de administración): `universidades_madrid: true`.
- **Tus títulos exactos** en `mis_titulos`: sirve para que, cuando una plaza exija un título
  de FP concreto, la IA te diga si el tuyo vale.
- **Palabras afines**: lo que hace que salga la etiqueta "Afín a ti".
- **Festivos**: añade cada año los traslados de festivos de la Comunidad de Madrid.

## Probar en tu ordenador

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # opcional
python -m radar.main --sin-telegram # o --dias 10 para mirar más atrás
# abre docs/index.html en el navegador
python -m unittest discover -s tests   # pruebas sin conexión
```

## Lo que conviene saber

- **DOCM y BOP de Toledo**: el DOCM prohíbe en su `robots.txt` que programas automáticos lean
  el sumario y los documentos, así que para la Junta de Castilla-La Mancha se usa su portal de
  empleo público (las mismas convocatorias, con su temario). El BOP de Toledo también parece
  restringirlo: el radar lo intenta y, si no le dejan, lo anota en `data/estado.json` y sigue con
  el BOE, que es donde se abre el plazo de Seseña e Illescas (perderás solo el aviso anticipado
  de las bases y el temario, que tendrás en el enlace del BOE).
- **Al añadir ayuntamientos o comunidades** en `config.yaml`, la siguiente ejecución vuelve a
  revisar las últimas 3 semanas y te manda un único resumen por Telegram.

- **Las fechas de cierre son estimaciones muy fiables, no oficiales**: se calculan con las
  reglas de la Ley 39/2015 y los festivos nacionales y de la Comunidad, pero no los locales.
  Antes de inscribirte, confirma en la convocatoria.
- **Dificultad y aspirantes son estimaciones de la IA**: el número real de presentados no se
  publica en el BOE; se basa en ediciones anteriores conocidas y en ratios típicos.
- **"Inscribirme" te lleva a la plataforma oficial**, no rellena nada por ti: allí eliges la
  convocatoria, entras con Cl@ve o certificado y pagas la tasa.
- **Ayuntamiento de Madrid**: publica sus bases en su propio boletín (BOAM), que el radar no lee;
  verás la convocatoria cuando salga el extracto en el BOE, con enlace a madrid.es/oposiciones
  para el temario.
- **Si el BOE o el BOCM cambian su web**, el radar puede dejar de encontrar cosas: el resumen de
  cada ejecución en *Actions* dice cuántos candidatos ha visto cada día. El código respeta el
  `robots.txt` de ambos boletines y espera entre peticiones.
- GitHub pausa las tareas programadas de repos sin actividad durante 60 días; como el radar
  guarda cambios a diario no debería pasar, pero si ocurre, se reactiva desde *Actions*.

## Estructura

```
config.yaml              ← lo que puedes cambiar
radar/
  main.py                ← ejecución diaria
  fuentes/boe.py, bocm.py← lectura de boletines
  filtros.py             ← descartes rápidos y ámbitos
  ia.py                  ← lectura con Claude (y modo básico sin IA)
  plazos.py              ← días hábiles/naturales y festivos
  procesos.py            ← junta anuncios en oposiciones y calcula su estado
  db.py                  ← SQLite
  telegram.py, web.py    ← avisos y datos de la web
docs/                    ← la web (index.html, styles.css, app.js, data.js)
data/radar.db            ← base de datos (la crea el radar)
.github/workflows/       ← ejecución automática diaria
tests/                   ← pruebas sin conexión
```
