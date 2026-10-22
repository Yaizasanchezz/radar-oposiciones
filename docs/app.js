(function () {
  "use strict";

  const datos = window.RADAR || { oposiciones: [], ambitos: {}, ayuntamientos: [], actualizado: "", hoy: "" };
  const hoy = datos.hoy ? new Date(datos.hoy + "T00:00:00") : new Date();
  const $ = (id) => document.getElementById(id);

  // ---------- almacenamiento local (archivadas y filtros) ----------
  const leer = (clave, defecto) => {
    try { return JSON.parse(localStorage.getItem(clave)) ?? defecto; } catch (e) { return defecto; }
  };
  const guardar = (clave, valor) => { try { localStorage.setItem(clave, JSON.stringify(valor)); } catch (e) { /* sin almacenamiento */ } };

  const archivadas = new Set(leer("radarArchivadas", []).map(String));
  const vista = Object.assign({ adm: "todas", seg: null, texto: "", afines: false }, leer("radarVista", {}));
  let abierta = null; // id de la oposición desplegada

  // ---------- utilidades ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const norm = (s) => String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const fecha = (iso, op) => iso ? new Date(iso + "T00:00:00").toLocaleDateString("es-ES", op || { day: "numeric", month: "short" }) : "";
  const fechaLarga = (iso) => fecha(iso, { day: "numeric", month: "long", year: "numeric" });
  const dias = (iso) => Math.round((new Date(iso + "T00:00:00") - hoy) / 86400000);
  const url = (u) => /^https?:\/\//i.test(u || "") ? u : "";
  const SEGMENTO = { abierta: "abiertas", proxima: "por_salir", prevista: "por_salir", consultar: "por_salir", cerrada: "cerradas" };
  const SISTEMA = { oposicion: "Oposición", "concurso-oposicion": "Concurso-oposición", concurso: "Concurso" };
  const PERSONAL = { funcionario: "Funcionario/a", laboral: "Laboral fijo", interino: "Interino/a", bolsa: "Bolsa de empleo" };

  const esAyto = (o) => o.ambito.startsWith("ayuntamiento_");
  const ops = datos.oposiciones;

  function enAdministracion(o) {
    const a = vista.adm;
    if (a === "archivadas") return archivadas.has(String(o.id));
    if (archivadas.has(String(o.id))) return false;
    if (a === "todas") return true;
    if (a === "aytos") return esAyto(o);
    return o.ambito === a;
  }

  function pasaBusqueda(o) {
    if (vista.afines && !o.afin) return false;
    const q = norm(vista.texto);
    return !q || norm([o.puesto, o.cuerpo, o.organismo, o.ambitoNombre, o.resumen].join(" ")).includes(q);
  }

  // ---------- cabecera ----------
  function pintarActualizado() {
    if (!datos.actualizado) { $("actualizado").textContent = "Todavía no se ha ejecutado el radar"; return; }
    const d = datos.actualizado.slice(0, 10), h = datos.actualizado.slice(11, 16);
    const cuando = d === datos.hoy ? "hoy" : "el " + fecha(d, { day: "numeric", month: "long" });
    $("actualizado").textContent = `Revisado ${cuando} a las ${h}`;
  }

  function pintarAdministraciones() {
    const activas = (f) => ops.filter((o) => !archivadas.has(String(o.id)) && SEGMENTO[o.estado] !== "cerradas" && f(o)).length;
    const amb = datos.ambitos || {};
    const ayto = (datos.ayuntamientos || []).find((x) => x.clave === vista.adm);
    const items = [
      ["todas", "Todas", activas(() => true)],
      amb.estatal && ["estatal", "Estado", activas((o) => o.ambito === "estatal")],
      amb.comunidad_madrid && ["comunidad_madrid", "C. de Madrid", activas((o) => o.ambito === "comunidad_madrid")],
      ["aytos", ayto ? ayto.nombre : "Ayuntamientos", activas(ayto ? (o) => o.ambito === ayto.clave : esAyto), true],
      amb.castilla_la_mancha && ["castilla_la_mancha", "Castilla-La Mancha", activas((o) => o.ambito === "castilla_la_mancha")],
      archivadas.size && ["archivadas", "Archivadas", ops.filter((o) => archivadas.has(String(o.id))).length],
    ].filter(Boolean);
    $("administraciones").innerHTML = items.map(([clave, texto, n, menu]) => {
      const activa = vista.adm === clave || (menu && (vista.adm === "aytos" || ayto));
      return `<button class="pestana" data-adm="${clave}" aria-pressed="${!!activa}"${menu ? ' aria-haspopup="dialog"' : ""}>` +
        `${esc(texto)}${n ? `<span class="n">${n}</span>` : ""}${menu ? '<span class="flecha" aria-hidden="true">▾</span>' : ""}</button>`;
    }).join("");
  }

  function pintarSegmentos(base) {
    const n = (s) => base.filter((o) => SEGMENTO[o.estado] === s).length;
    if (!vista.seg || vista.adm === "archivadas") vista.seg = n("abiertas") ? "abiertas" : n("por_salir") ? "por_salir" : "abiertas";
    const segs = [["abiertas", "Abiertas"], ["por_salir", "Por salir"], ["cerradas", "Cerradas"]];
    $("segmentos").innerHTML = segs.map(([s, t]) =>
      `<button class="segmento" role="tab" data-seg="${s}" aria-selected="${vista.seg === s}">${t}${n(s) ? `<span class="n">${n(s)}</span>` : ""}</button>`
    ).join("");
  }

  // ---------- fila de una oposición ----------
  function plazo(o) {
    if (o.estado === "abierta" && o.finPlazo) {
      const d = dias(o.finPlazo);
      return { clase: d <= 3 ? "urgente" : "", num: d, txt: d === 0 ? "último día" : d === 1 ? "día" : "días" };
    }
    if (o.estado === "abierta") return { clase: "", num: "Abierta", txt: "fin por confirmar" };
    if (o.estado === "proxima" && o.inicioPlazo) return { clase: "por-salir", num: fecha(o.inicioPlazo), txt: "abre" };
    if (o.estado === "proxima") return { clase: "por-salir", num: "Bases", txt: "falta el BOE" };
    if (o.estado === "prevista") return { clase: "por-salir", num: "Prevista", txt: "en la oferta" };
    if (o.estado === "cerrada") return { clase: "cerrada", num: o.finPlazo ? fecha(o.finPlazo) : "Cerrada", txt: o.finPlazo ? "cerró" : "" };
    return { clase: "consultar", num: "Revisar", txt: "plazo" };
  }

  function lineaPlazo(o) {
    if (o.estado === "abierta") {
      return o.finPlazo ? `Puedes inscribirte hasta el <strong>${fechaLarga(o.finPlazo)}</strong>${o.plazoTexto ? ` (${esc(o.plazoTexto)})` : ""}.`
        : "El plazo está abierto. Confirma la fecha de cierre en la convocatoria.";
    }
    if (o.estado === "proxima" && o.inicioPlazo) return `El plazo se abre el <strong>${fechaLarga(o.inicioPlazo)}</strong>.`;
    if (o.estado === "proxima") return "Ya hay bases. El plazo se abrirá cuando salga el extracto en el BOE." + (o.aperturaEstimada ? ` ${esc(o.aperturaEstimada)}` : "");
    if (o.estado === "prevista") return "Está en la oferta de empleo público, pero aún no se ha convocado." + (o.aperturaEstimada ? ` ${esc(o.aperturaEstimada)}` : "");
    if (o.estado === "cerrada") return o.finPlazo ? `El plazo terminó el ${fechaLarga(o.finPlazo)}.` : "El plazo ya terminó.";
    return "Revisa el anuncio para conocer el plazo.";
  }

  function grupo(o) {
    if (!o.subgrupo || o.subgrupo === "DESCONOCIDO") return "";
    return o.subgrupo === "LABORAL" ? (o.grupoLaboral || "Laboral") : o.subgrupo;
  }

  function detalle(o) {
    const p = [];
    const clase = o.estado === "abierta" ? "" : o.estado === "cerrada" ? "cerrada" : "por-salir";
    p.push(`<p class="linea-plazo ${clase}">${lineaPlazo(o)}</p>`);
    if (o.accesible === "dudoso" && o.motivoAccesible) p.push(`<p class="aviso-req">${esc(o.motivoAccesible)}</p>`);

    const ficha = [];
    if (o.cuerpo && norm(o.cuerpo) !== norm(o.puesto)) ficha.push(["Cuerpo", esc(o.cuerpo)]);
    if (o.plazas) ficha.push(["Plazas", o.plazas]);
    if (SISTEMA[o.sistema]) ficha.push(["Sistema", SISTEMA[o.sistema]]);
    if (PERSONAL[o.personal]) ficha.push(["Personal", PERSONAL[o.personal]]);
    if (o.titulacion) ficha.push(["Titulación", esc(o.titulacion)]);
    if (o.tasa) ficha.push(["Tasa", o.tasa.toLocaleString("es-ES") + " €"]);
    if (o.dificultad && o.dificultad.nivel) {
      const n = Math.max(1, Math.min(5, o.dificultad.nivel));
      ficha.push(["Dificultad", `<span class="estrellas" aria-label="${n} de 5">${"★".repeat(n)}${"☆".repeat(5 - n)}</span>`]);
    }
    if (o.aspirantes && o.aspirantes.estimacion) ficha.push(["Aspirantes", esc(o.aspirantes.estimacion)]);
    if (ficha.length) p.push(`<dl class="ficha">${ficha.map(([a, b]) => `<dt>${a}</dt><dd>${b}</dd>`).join("")}</dl>`);

    const t = o.temario || {};
    if (t.disponible && (t.bloques || []).length) {
      p.push(`<div class="bloque"><h3>Temario${t.num_temas ? `, ${t.num_temas} temas` : ""}</h3><ul>` +
        t.bloques.map((b) => `<li><strong>${esc(b.nombre)}</strong>${b.num_temas ? ` (${b.num_temas})` : ""}: ${esc(b.resumen)}</li>`).join("") + "</ul></div>");
    } else if (t.disponible && t.num_temas) {
      p.push(`<div class="bloque"><h3>Temario, ${t.num_temas} temas</h3><p>El detalle está en las bases.</p></div>`);
    }
    if ((o.ejercicios || []).length) {
      p.push(`<div class="bloque"><h3>Ejercicios</h3><ul>` +
        o.ejercicios.map((e) => `<li><strong>${esc(e.nombre)}</strong>: ${esc(e.descripcion)}</li>`).join("") + "</ul></div>");
    }
    const notas = [];
    if (o.dificultad && o.dificultad.explicacion && o.dificultad.nivel) notas.push(esc(o.dificultad.explicacion));
    if (o.aspirantes && o.aspirantes.explicacion) notas.push(esc(o.aspirantes.explicacion));
    if (o.requisitos) notas.push("Otros requisitos: " + esc(o.requisitos));
    if (notas.length) p.push(`<div class="bloque"><h3>A tener en cuenta</h3>${notas.map((n) => `<p>${n}</p>`).join("")}<p class="nota">Dificultad y aspirantes son estimaciones.</p></div>`);

    const acc = [];
    const insc = url(o.urlInscripcion);
    if (o.estado === "abierta" && insc) acc.push(`<a class="boton principal" href="${esc(insc)}" target="_blank" rel="noopener">Inscribirme</a>`);
    for (const e of o.enlaces.slice().reverse()) {
      const u = url(e.url);
      if (u) acc.push(`<a class="boton" href="${esc(u)}" target="_blank" rel="noopener" title="${esc(e.titulo)}">${esc(e.fuente)} del ${fecha(e.fecha)}</a>`);
    }
    const arch = archivadas.has(String(o.id));
    acc.push(`<button class="boton archivar" data-archivar="${o.id}">${arch ? "Recuperar" : "Archivar"}</button>`);
    p.push(`<div class="acciones">${acc.join("")}</div>`);
    return p.join("");
  }

  function fila(o) {
    const pl = plazo(o);
    const g = grupo(o);
    const desplegada = abierta === String(o.id);
    const datosFila = [
      g && `<span class="grupo">${esc(g)}</span>`,
      o.plazas && `<span>${o.plazas} ${o.plazas === 1 ? "plaza" : "plazas"}</span>`,
      o.afin && "<span>Afín a ti</span>",
      o.accesible === "dudoso" && '<span class="dudoso">Revisa requisitos</span>',
    ].filter(Boolean).join("");
    return `<li class="opo ${o.estado}">
      <button class="opo-cabeza" data-abrir="${o.id}" aria-expanded="${desplegada}" aria-controls="d${o.id}">
        <span class="opo-titulo">${esc(o.puesto)}${o.nuevo && o.estado !== "cerrada" ? '<span class="opo-nueva" title="Nueva"></span>' : ""}</span>
        <span class="plazo ${pl.clase}"><span class="plazo-num">${esc(pl.num)}</span><span class="plazo-txt">${esc(pl.txt)}</span></span>
        <span class="opo-org">${esc(o.ambitoNombre)}</span>
        ${datosFila ? `<span class="opo-datos">${datosFila}</span>` : ""}
      </button>
      <div class="opo-detalle" id="d${o.id}"${desplegada ? "" : " hidden"}>${desplegada ? detalle(o) : ""}</div>
    </li>`;
  }

  // ---------- lista ----------
  function pintar() {
    pintarAdministraciones();
    const base = ops.filter((o) => enAdministracion(o) && pasaBusqueda(o));
    const archivo = vista.adm === "archivadas";
    $("segmentos").hidden = archivo;
    pintarSegmentos(base);
    const lista = archivo ? base : base.filter((o) => SEGMENTO[o.estado] === vista.seg);

    const ayto = (datos.ayuntamientos || []).find((x) => x.clave === vista.adm);
    let resumen = "";
    if (ayto) resumen = `Solo Ayto. ${esc(ayto.nombre)}. <button data-adm-reset>Ver todos los ayuntamientos</button>`;
    else if (archivo) resumen = "Oposiciones que has archivado. Ábrelas para recuperarlas.";
    $("resumenFiltro").innerHTML = resumen;
    $("resumenFiltro").hidden = !resumen;

    if (!lista.length) {
      const msg = !ops.length ? ["Aún no hay datos", "Cuando el radar haga su revisión diaria aparecerán aquí."]
        : vista.seg === "abiertas" && !archivo ? ["Nada abierto ahora mismo", "Mira en «Por salir» lo que se espera, o revisa otra administración."]
        : ["No hay oposiciones aquí", vista.texto || vista.afines ? "Prueba a quitar la búsqueda." : "Prueba con otra administración o estado."];
      $("lista").innerHTML = `<li class="vacio"><strong>${msg[0]}</strong>${msg[1]}</li>`;
    } else {
      $("lista").innerHTML = lista.map(fila).join("");
    }
    guardar("radarVista", { adm: vista.adm, seg: vista.seg, afines: vista.afines });
  }

  // ---------- hojas ----------
  function ultimoBOE() {
    const d = new Date(hoy);
    if (d.getDay() === 0) d.setDate(d.getDate() - 1); // el BOE no sale en domingo
    const p = (n) => String(n).padStart(2, "0");
    return `https://www.boe.es/boe/dias/${d.getFullYear()}/${p(d.getMonth() + 1)}/${p(d.getDate())}/index.php?s=2B`;
  }

  function pintarBoletines() {
    const g = (t) => `<li class="grupo-enlaces">${t}</li>`;
    const e = (href, titulo, desc) => `<li><a href="${esc(href)}" target="_blank" rel="noopener"><strong>${titulo}</strong><span>${desc}</span></a></li>`;
    $("enlacesBoletines").innerHTML = [
      g("Estado"),
      e(ultimoBOE(), "BOE: oposiciones y concursos de hoy", "Sección II.B del último BOE"),
      e("https://administracion.gob.es/PAG/ips", "Inscripción en pruebas selectivas (IPS)", "Donde te inscribes a las oposiciones del Estado"),
      g("Comunidad de Madrid"),
      e("https://www.bocm.es/ultimo-bocm", "Último BOCM", "Mira «Autoridades y Personal» y «Administración Local»"),
      e("https://www.comunidad.madrid/servicios/empleo/oposiciones-administracion-servicios-comunidad-madrid", "Oposiciones de la Comunidad de Madrid", "Convocatorias e inscripción"),
      g("Castilla-La Mancha"),
      e("https://docm.jccm.es/docm/sumario.do", "DOCM de hoy", "Busca «II. Autoridades y Personal» y «1. Oposiciones y Concursos»"),
      e("https://empleopublico.castillalamancha.es/procesos-selectivos/abiertos/turno-libre", "Procesos selectivos de la Junta", "Portal de empleo público, turno libre"),
      e("https://docm.jccm.es/docm/alertas.do", "Alertas del DOCM por correo", "Suscríbete a «Oposiciones y Concursos»"),
      e("https://bop.diputoledo.es/webEbop/ebop.jsp", "BOP de Toledo", "Bases de Seseña, Illescas y otros pueblos de Toledo"),
    ].join("");
  }

  function pintarAytos() {
    const lista = datos.ayuntamientos || [];
    const cuenta = (c) => ops.filter((o) => o.ambito === c && !archivadas.has(String(o.id)) && SEGMENTO[o.estado] !== "cerradas").length;
    const porRegion = [["bocm", "Comunidad de Madrid"], ["bop_toledo", "Provincia de Toledo"]];
    const html = [`<li class="ayto"><button class="ayto-ver" data-ayto="aytos"><strong>Todos los ayuntamientos</strong><span>${lista.length} vigilados</span></button></li>`];
    for (const [b, nombre] of porRegion) {
      const grupoAytos = lista.filter((a) => a.boletin === b);
      if (!grupoAytos.length) continue;
      html.push(`<li class="ayto-grupo">${nombre}</li>`);
      for (const a of grupoAytos) {
        const n = cuenta(a.clave);
        html.push(`<li class="ayto"><button class="ayto-ver" data-ayto="${a.clave}"><strong>${esc(a.nombre)}</strong>` +
          `<span>${n ? `${n} ${n === 1 ? "oposición activa" : "oposiciones activas"}` : "Nada activo ahora"}</span></button>` +
          (a.boletin === "bop_toledo" && url(a.urlBoletin) ? `<a href="${esc(a.urlBoletin)}" target="_blank" rel="noopener" title="Sus anuncios en el BOP de Toledo">BOP</a>` : "") +
          (url(a.urlEmpleo) ? `<a href="${esc(a.urlEmpleo)}" target="_blank" rel="noopener">Web</a>` : "") + "</li>");
      }
    }
    $("listaAytos").innerHTML = html.join("");
  }

  function abrirHoja(id) {
    const h = $(id);
    if (typeof h.showModal === "function") h.showModal(); else h.setAttribute("open", "");
  }
  function cerrarHoja(h) { if (typeof h.close === "function") h.close(); else h.removeAttribute("open"); }

  // ---------- archivar ----------
  let temporizador;
  function archivar(id) {
    const ya = archivadas.has(id);
    if (ya) archivadas.delete(id); else archivadas.add(id);
    guardar("radarArchivadas", [...archivadas]);
    if (!ya) abierta = null;
    if (vista.adm === "archivadas" && !archivadas.size) vista.adm = "todas";
    pintar();
    const aviso = $("avisoFlotante");
    aviso.innerHTML = `${ya ? "Recuperada" : "Archivada"} <button data-deshacer="${id}">Deshacer</button>`;
    aviso.hidden = false;
    clearTimeout(temporizador);
    temporizador = setTimeout(() => { aviso.hidden = true; }, 4000);
  }

  // ---------- eventos ----------
  document.addEventListener("click", (ev) => {
    const t = ev.target.closest("[data-adm],[data-seg],[data-abrir],[data-archivar],[data-deshacer],[data-ayto],[data-cerrar],[data-adm-reset]");
    if (!t) return;
    if (t.dataset.adm) {
      if (t.dataset.adm === "aytos") { pintarAytos(); abrirHoja("hojaAytos"); return; }
      vista.adm = t.dataset.adm; vista.seg = null; abierta = null; pintar();
    } else if (t.hasAttribute("data-adm-reset")) {
      vista.adm = "aytos"; vista.seg = null; pintar();
    } else if (t.dataset.ayto) {
      vista.adm = t.dataset.ayto; vista.seg = null; abierta = null;
      cerrarHoja($("hojaAytos")); pintar();
    } else if (t.dataset.seg) {
      vista.seg = t.dataset.seg; abierta = null; pintar();
    } else if (t.dataset.abrir) {
      abierta = abierta === t.dataset.abrir ? null : t.dataset.abrir; pintar();
    } else if (t.dataset.archivar) {
      archivar(t.dataset.archivar);
    } else if (t.dataset.deshacer) {
      archivar(t.dataset.deshacer); $("avisoFlotante").hidden = true;
    } else if (t.hasAttribute("data-cerrar")) {
      cerrarHoja(t.closest("dialog"));
    }
  });

  for (const h of document.querySelectorAll("dialog")) {
    h.addEventListener("click", (ev) => { if (ev.target === h) cerrarHoja(h); }); // tocar fuera cierra
  }

  $("abrirBoletines").addEventListener("click", () => { pintarBoletines(); abrirHoja("hojaBoletines"); });
  $("abrirBuscar").addEventListener("click", () => {
    const b = $("buscador");
    b.hidden = !b.hidden;
    $("abrirBuscar").setAttribute("aria-expanded", String(!b.hidden));
    if (!b.hidden) $("buscar").focus();
  });
  $("buscar").addEventListener("input", (ev) => { vista.texto = ev.target.value; pintar(); });
  $("soloAfines").checked = vista.afines;
  $("soloAfines").addEventListener("change", (ev) => { vista.afines = ev.target.checked; pintar(); });
  if (vista.afines) { $("buscador").hidden = false; $("abrirBuscar").setAttribute("aria-expanded", "true"); }

  // Una administración guardada que ya no existe vuelve a "Todas"
  const validas = ["todas", "aytos", "archivadas", ...Object.keys(datos.ambitos || {})];
  if (!validas.includes(vista.adm) || (vista.adm === "archivadas" && !archivadas.size)) vista.adm = "todas";
  vista.seg = null;

  pintarActualizado();
  pintar();
})();
