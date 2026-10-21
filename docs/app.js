(function () {
  "use strict";

  const datos = window.RADAR || { oposiciones: [], ambitos: {}, actualizado: "", hoy: "" };
  const hoy = datos.hoy ? new Date(datos.hoy + "T00:00:00") : new Date();

  const ESTADOS = [
    ["todas", "Todas"],
    ["abierta", "Abiertas"],
    ["proxima", "Próximas"],
    ["prevista", "Previstas"],
    ["consultar", "Por confirmar"],
    ["cerrada", "Cerradas"],
  ];
  const NOMBRE_SISTEMA = { oposicion: "Oposición", "concurso-oposicion": "Concurso-oposición", concurso: "Concurso" };
  const NOMBRE_PERSONAL = { funcionario: "Funcionario/a", laboral: "Laboral fijo", interino: "Interino/a", bolsa: "Bolsa de empleo" };
  const NOMBRE_ESTADO = {
    abierta: "Abierta", proxima: "Próxima", prevista: "Prevista (OEP)",
    consultar: "Plazo por confirmar", cerrada: "Cerrada",
  };

  const filtros = { estado: "todas", texto: "", ambito: "", subgrupo: "", afines: false };
  try {
    const guardado = JSON.parse(localStorage.getItem("radarFiltros") || "{}");
    Object.assign(filtros, guardado);
  } catch (e) { /* sin almacenamiento local */ }

  // ---------- utilidades ----------
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const norm = (s) => String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const fecha = (iso, opciones) => iso
    ? new Date(iso + "T00:00:00").toLocaleDateString("es-ES", opciones || { day: "numeric", month: "short", year: "numeric" })
    : "";
  const diasHasta = (iso) => Math.round((new Date(iso + "T00:00:00") - hoy) / 86400000);
  const urlSegura = (u) => /^https?:\/\//i.test(u || "") ? u : "";

  function guardarFiltros() {
    try { localStorage.setItem("radarFiltros", JSON.stringify(filtros)); } catch (e) { /* nada */ }
  }

  // ---------- cabecera ----------
  function pintarCabecera() {
    const nombres = Object.values(datos.ambitos || {});
    if (nombres.length) $("subtitulo").textContent = "C1 · C2 · AP — " + nombres.join(" · ");
    $("actualizado").textContent = datos.actualizado
      ? "Actualizado el " + fecha(datos.actualizado.slice(0, 10), { day: "numeric", month: "long" }) +
        " a las " + datos.actualizado.slice(11, 16)
      : "Todavía no se ha ejecutado el radar";
    const cuenta = (e) => datos.oposiciones.filter((o) => o.estado === e).length;
    $("contadores").innerHTML = [
      ["abierta", "abiertas"], ["proxima", "próximas"], ["prevista", "previstas"],
    ].map(([e, t]) => `<span class="contador"><b>${cuenta(e)}</b>${t}</span>`).join("");

    const sel = $("filtroAmbito");
    for (const [clave, nombre] of Object.entries(datos.ambitos || {})) {
      const op = document.createElement("option");
      op.value = clave; op.textContent = nombre;
      sel.appendChild(op);
    }
  }

  function pintarChips() {
    $("chipsEstado").innerHTML = ESTADOS.map(([v, t]) =>
      `<button class="chip" role="tab" data-estado="${v}" aria-selected="${filtros.estado === v}">${t}</button>`
    ).join("");
  }

  // ---------- tarjetas ----------
  function textoPlazo(o) {
    if (o.estado === "abierta") {
      if (!o.finPlazo) return "Inscripción <b>abierta</b> · fecha de cierre por confirmar";
      const d = diasHasta(o.finPlazo);
      const quedan = d === 0 ? "¡último día!" : d === 1 ? "queda 1 día" : `quedan ${d} días`;
      return `Inscripción <b>abierta hasta el ${fecha(o.finPlazo)}</b> (${quedan})`;
    }
    if (o.estado === "proxima" && o.inicioPlazo) return `Se abre el <b>${fecha(o.inicioPlazo)}</b>`;
    if (o.estado === "proxima") {
      return "Bases publicadas; el plazo se abrirá cuando salga el extracto en el BOE" +
        (o.aperturaEstimada ? `<br><span class="nota">${esc(o.aperturaEstimada)}</span>` : "");
    }
    if (o.estado === "prevista") {
      return "Incluida en la Oferta de Empleo Público, aún sin convocar" +
        (o.aperturaEstimada ? `<br><span class="nota">${esc(o.aperturaEstimada)}</span>` : "");
    }
    if (o.estado === "cerrada") return o.finPlazo ? `Plazo cerrado el ${fecha(o.finPlazo)}` : "Plazo cerrado";
    return "Revisa el anuncio para conocer el plazo";
  }

  function tarjeta(o) {
    const etiquetas = [
      `<span class="etiqueta estado-${o.estado}">${NOMBRE_ESTADO[o.estado] || o.estado}</span>`,
      o.subgrupo && o.subgrupo !== "DESCONOCIDO"
        ? `<span class="etiqueta subgrupo">${esc(o.subgrupo === "LABORAL" ? (o.grupoLaboral || "Laboral") : o.subgrupo)}</span>` : "",
      `<span class="etiqueta">${esc(o.ambitoNombre)}</span>`,
      o.nuevo && o.estado !== "cerrada" ? `<span class="etiqueta nuevo">Nueva</span>` : "",
      o.afin ? `<span class="etiqueta afin">Afín a ti</span>` : "",
    ].join("");

    const filas = [];
    if (o.plazas) filas.push(["Plazas", o.plazas]);
    if (NOMBRE_SISTEMA[o.sistema]) filas.push(["Sistema", NOMBRE_SISTEMA[o.sistema]]);
    if (NOMBRE_PERSONAL[o.personal]) filas.push(["Personal", NOMBRE_PERSONAL[o.personal]]);
    const boe = o.enlaces.find((e) => e.fuente === "BOE");
    filas.push(boe ? ["Publicada en BOE", fecha(boe.fecha)] : ["Publicada en " + (o.enlaces[0]?.fuente || ""), fecha(o.publicado)]);
    if (o.plazoTexto) filas.push(["Plazo", o.plazoTexto]);
    if (o.tasa) filas.push(["Tasa", o.tasa.toLocaleString("es-ES") + " €"]);
    if (o.dificultad && o.dificultad.nivel) {
      const n = Math.max(1, Math.min(5, o.dificultad.nivel));
      filas.push(["Dificultad", `<span class="estrellas" title="${esc(o.dificultad.explicacion)}">${"★".repeat(n)}${"☆".repeat(5 - n)}</span>`]);
    }
    if (o.aspirantes && o.aspirantes.estimacion) filas.push(["Aspirantes", esc(o.aspirantes.estimacion) + " <span class=\"nota\">(estim.)</span>"]);

    const t = o.temario || {};
    let temario = "";
    if (t.disponible && (t.bloques || []).length) {
      temario = `<details><summary>Temario${t.num_temas ? " · " + t.num_temas + " temas" : ""}</summary><ul>` +
        t.bloques.map((b) => `<li><b>${esc(b.nombre)}</b>${b.num_temas ? ` (${b.num_temas} temas)` : ""}: ${esc(b.resumen)}</li>`).join("") +
        "</ul></details>";
    } else if (t.disponible && t.num_temas) {
      temario = `<details><summary>Temario · ${t.num_temas} temas</summary><p>Consulta el detalle en el anuncio oficial.</p></details>`;
    } else if (o.estado !== "prevista") {
      temario = `<p class="nota">Temario: no viene en este anuncio; está en las bases enlazadas.</p>`;
    }

    const ejercicios = (o.ejercicios || []).length
      ? `<details><summary>Ejercicios (${o.ejercicios.length})</summary><ul>` +
        o.ejercicios.map((e) => `<li><b>${esc(e.nombre)}</b>: ${esc(e.descripcion)}</li>`).join("") + "</ul></details>"
      : "";

    const mas = [];
    if (o.dificultad && o.dificultad.explicacion && o.dificultad.nivel) mas.push(`<p><b>Dificultad:</b> ${esc(o.dificultad.explicacion)}</p>`);
    if (o.aspirantes && o.aspirantes.explicacion) mas.push(`<p><b>Aspirantes:</b> ${esc(o.aspirantes.explicacion)}</p>`);
    if (o.titulacion) mas.push(`<p><b>Titulación:</b> ${esc(o.titulacion)}</p>`);
    if (o.requisitos) mas.push(`<p><b>Otros requisitos:</b> ${esc(o.requisitos)}</p>`);
    if (o.resumen) mas.push(`<p>${esc(o.resumen)}</p>`);
    const detalles = mas.length ? `<details><summary>Más detalles</summary>${mas.join("")}<p class="nota">Dificultad y aspirantes son estimaciones orientativas.</p></details>` : "";

    const botones = [];
    const insc = urlSegura(o.urlInscripcion);
    if (o.estado === "abierta" && insc) botones.push(`<a class="boton principal" href="${esc(insc)}" target="_blank" rel="noopener">Inscribirme →</a>`);
    for (const e of o.enlaces.slice().reverse()) {
      const u = urlSegura(e.url);
      if (u) botones.push(`<a class="boton" href="${esc(u)}" target="_blank" rel="noopener" title="${esc(e.titulo)}">${esc(e.fuente)} ${fecha(e.fecha, { day: "numeric", month: "short" })}</a>`);
    }

    return `<article class="tarjeta ${o.estado}">
      <div class="etiquetas">${etiquetas}</div>
      <h2>${esc(o.puesto)}</h2>
      <p class="organismo">${esc(o.organismo)}${o.cuerpo && norm(o.cuerpo) !== norm(o.puesto) ? " · " + esc(o.cuerpo) : ""}</p>
      <div class="plazo ${o.estado}">${textoPlazo(o)}</div>
      ${o.accesible === "dudoso" ? `<div class="aviso-req">Revisa los requisitos: ${esc(o.motivoAccesible)}</div>` : ""}
      <dl class="datos">${filas.map(([a, b]) => `<dt>${esc(a)}</dt><dd>${b}</dd>`).join("")}</dl>
      ${temario}${ejercicios}${detalles}
      <div class="botones">${botones.join("")}</div>
    </article>`;
  }

  function pintarLista() {
    const q = norm(filtros.texto);
    const lista = datos.oposiciones.filter((o) =>
      (filtros.estado === "todas" || o.estado === filtros.estado) &&
      (!filtros.ambito || o.ambito === filtros.ambito) &&
      (!filtros.subgrupo || o.subgrupo === filtros.subgrupo) &&
      (!filtros.afines || o.afin) &&
      (!q || norm([o.puesto, o.cuerpo, o.organismo, o.ambitoNombre, o.resumen].join(" ")).includes(q))
    );
    $("lista").innerHTML = lista.length
      ? lista.map(tarjeta).join("")
      : `<div class="vacio">${datos.oposiciones.length
          ? "No hay oposiciones con estos filtros."
          : "Aún no hay datos. En cuanto el radar se ejecute aparecerán aquí las oposiciones."}</div>`;
  }

  // ---------- eventos ----------
  function iniciar() {
    pintarCabecera();
    pintarChips();
    $("buscar").value = filtros.texto;
    $("filtroAmbito").value = filtros.ambito;
    $("filtroSubgrupo").value = filtros.subgrupo;
    $("soloAfines").checked = filtros.afines;

    $("chipsEstado").addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-estado]");
      if (!b) return;
      filtros.estado = b.dataset.estado;
      pintarChips(); pintarLista(); guardarFiltros();
    });
    $("buscar").addEventListener("input", (ev) => { filtros.texto = ev.target.value; pintarLista(); guardarFiltros(); });
    $("filtroAmbito").addEventListener("change", (ev) => { filtros.ambito = ev.target.value; pintarLista(); guardarFiltros(); });
    $("filtroSubgrupo").addEventListener("change", (ev) => { filtros.subgrupo = ev.target.value; pintarLista(); guardarFiltros(); });
    $("soloAfines").addEventListener("change", (ev) => { filtros.afines = ev.target.checked; pintarLista(); guardarFiltros(); });
    pintarLista();
  }

  iniciar();
})();
