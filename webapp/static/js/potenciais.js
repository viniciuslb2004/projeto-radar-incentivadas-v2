// Aba "Potenciais Linhas" (v2, 2026-09-25): usuario informa o perfil do projeto e
// recebe linhas do catalogo com "potencial aderência" -- NUNCA "elegibilidade
// confirmada". Motor 100% deterministico em webapp/potenciais.py (regras duras
// excluem, criterios verificados viram chips ✓ / –). Resultados atualizam sem
// recarregar a cada mudanca do formulario (debounce). "Transações semelhantes"
// reaproveita /api/operacoes. Helpers de texto (lnResumo*, lnCortarNaPalavra)
// vivem em linhas.js.

let potenciaisOpcoesCarregadas = false;
let _ptSetorPorAtividade = {};
const _PT_CAMPOS = {
  atividade: "pt-f-atividade", finalidade: "pt-f-finalidade", tomador: "pt-f-tomador",
  porte: "pt-f-porte", uf: "pt-f-uf", volume: "pt-f-volume",
};
const _PT_EXEMPLOS = [
  { rotulo: "Pequena indústria em SP comprando máquinas (R$ 2 mi)", v: { atividade: "industria", finalidade: "maquinas", porte: "PEQUENA", uf: "SP", volume: "2" } },
  { rotulo: "Geradora eólica no RN (R$ 500 mi)", v: { atividade: "energia", finalidade: "investimento", porte: "GRANDE", uf: "RN", volume: "500" } },
  { rotulo: "Hospital na BA, expansão (R$ 80 mi)", v: { atividade: "saude", finalidade: "investimento", porte: "GRANDE", uf: "BA", volume: "80" } },
  { rotulo: "Micro varejo em PE, capital de giro (R$ 200 mil)", v: { atividade: "comercio", finalidade: "giro", porte: "MICRO", uf: "PE", volume: "0,2" } },
];

function _ptFill(id, itens) {
  const sel = document.getElementById(id);
  if (!sel) return;
  itens.forEach(([valor, rotulo]) => {
    const opt = document.createElement("option");
    opt.value = valor;
    opt.textContent = rotulo;
    sel.appendChild(opt);
  });
}

async function _initPotenciaisOpcoes() {
  if (potenciaisOpcoesCarregadas) return;
  let opcoes;
  try {
    opcoes = await fetchJSON("/api/potenciais/opcoes");
  } catch (e) {
    return;
  }
  (opcoes.atividades || []).forEach((a) => { _ptSetorPorAtividade[a.id] = a.setor; });
  _ptFill("pt-f-atividade", (opcoes.atividades || []).map((a) => [a.id, a.rotulo]));
  _ptFill("pt-f-finalidade", (opcoes.finalidades || []).map((f) => [f.id, f.rotulo]));
  _ptFill("pt-f-tomador", (opcoes.tomadores || []).map((t) => [t.id, t.rotulo]));
  _ptFill("pt-f-uf", (opcoes.ufs || []).map((u) => [u, u]));
  potenciaisOpcoesCarregadas = true;
  _aplicarFiltrosPotenciaisDaURL();
}

function _aplicarFiltrosPotenciaisDaURL() {
  if (_viewInicialDaURL() !== "potenciais") { _ptRenderVazio(); return; }
  const params = paramsDaURL();
  let algum = false;
  Object.entries(_PT_CAMPOS).forEach(([chave, id]) => {
    const el = document.getElementById(id);
    if (el && params.has(chave)) { el.value = params.get(chave); algum = algum || !!el.value; }
  });
  if (algum) _buscarPotenciais(); else _ptRenderVazio();
}

function _ptForm() {
  const f = {};
  Object.entries(_PT_CAMPOS).forEach(([chave, id]) => { f[chave] = (document.getElementById(id)?.value || "").trim(); });
  return f;
}

function _ptParseValorMM(txt) {
  if (!txt) return null;
  const n = Number(String(txt).replace(/\./g, "").replace(",", "."));
  return Number.isFinite(n) && n > 0 ? n : NaN;
}

function _ptRenderVazio() {
  const box = document.getElementById("pt-resultado");
  if (!box) return;
  box.innerHTML = `<div class="pt-vazio">
    <p>Preencha o perfil acima para ver as linhas de crédito incentivado com maior potencial de aderência.</p>
    <div class="pt-exemplos">${_PT_EXEMPLOS.map((e, i) => `<button type="button" class="pt-exemplo" data-exemplo="${i}">${esc(e.rotulo)}</button>`).join("")}</div>
  </div>`;
  box.querySelectorAll("[data-exemplo]").forEach((b) => b.addEventListener("click", () => {
    const ex = _PT_EXEMPLOS[Number(b.dataset.exemplo)].v;
    Object.entries(_PT_CAMPOS).forEach(([chave, id]) => {
      const el = document.getElementById(id);
      if (el && chave !== "tomador") el.value = ex[chave] || "";
    });
    _buscarPotenciais();
  }));
}

function _ptSeloClasse(rotulo) {
  return rotulo === "Alta" ? "pt-selo-alta" : rotulo === "Média" ? "pt-selo-media" : "pt-selo-baixa";
}

// Linha de atributos-chave: so o que a fonte informa (numero literal extraido ou
// corte curto); o que faltar vai pra um "Não informado: ..." discreto.
function _ptAtributos(l) {
  const partes = [];
  const faltando = [];
  const add = (rot, resumo, bruto) => {
    if (lnNaoInformado(bruto)) { faltando.push(rot.toLowerCase()); return; }
    partes.push(`<span class="rot">${esc(rot)}</span> ${esc(resumo || lnCortarNaPalavra(bruto, 40))}`);
  };
  add("Prazo", lnResumoDuracao(l.prazo_total), l.prazo_total);
  add("Carência", lnResumoDuracao(l.carencia), l.carencia);
  add("Participação", lnResumoPercentual(l.percentual_financiavel), l.percentual_financiavel);
  const taxaBruta = lnNaoInformado(l.taxa_completa) ? l.indexador : l.taxa_completa;
  add("Taxa", lnResumoTaxa(l.taxa_completa, l.indexador), taxaBruta);
  let html = partes.join('<span class="sep" aria-hidden="true">·</span>');
  if (faltando.length) html += `${partes.length ? '<span class="sep" aria-hidden="true">·</span>' : ""}<span class="rot">Não informado: ${esc(faltando.join(", "))}</span>`;
  return html;
}

function _ptDetalhesCondicoes(l) {
  const itens = [["Taxa", l.taxa_completa], ["Prazo", l.prazo_total], ["Carência", l.carencia], ["Participação", l.percentual_financiavel]]
    .filter(([, v]) => !lnNaoInformado(v));
  if (!itens.length) return "";
  return `<dl class="pt-detalhes" hidden>${itens.map(([r, v]) => `<dt>${esc(r)}</dt><dd>${esc(v)}</dd>`).join("")}
    ${l.url_oficial ? `<dd style="margin-top:8px;"><a href="${escUrl(l.url_oficial)}" target="_blank" rel="noopener noreferrer">Fonte oficial ↗</a></dd>` : ""}</dl>`;
}

function _ptCard(l) {
  const crit = (l.criterios || []).map((c) => {
    const ok = c.status === "ok";
    return `<li class="${ok ? "ok" : "na"}"><span class="ic" aria-hidden="true">${ok ? "✓" : "–"}</span><span><span class="sr-only">${ok ? "Atende: " : "Não informado: "}</span>${esc(c.texto)}</span></li>`;
  }).join("");
  const alertas = (l.alertas || []).map((a) => `<p class="pt-alerta">⚠ ${esc(a)}</p>`).join("");
  const freq = l.frequencia_historica >= 10 ? ` · ~${fmtNum(l.frequencia_historica)} operações parecidas na base` : "";
  const detalhes = _ptDetalhesCondicoes(l);
  return `<article class="pt-card" data-id="${esc(l.id)}">
    <div class="pt-card-topo">
      <div>
        <h3>${esc(l.nome)}</h3>
        <div class="pt-inst">${esc(l.instituicao)} · ${l.fluxo === "edital" ? "Edital" : "Fluxo contínuo"}${esc(freq)}</div>
      </div>
      <span class="pt-selo ${_ptSeloClasse(l.score_rotulo)}" title="Potencial aderência calculada pelos critérios verificados">Aderência ${esc(l.score_rotulo).toLowerCase()} · ${esc(l.score_pct)}%</span>
    </div>
    <p class="pt-attrs">${_ptAtributos(l)}</p>
    <ul class="pt-crit" aria-label="Critérios avaliados">${crit}</ul>
    ${alertas}
    <div class="pt-acoes">
      ${detalhes ? `<button type="button" class="pt-btn" data-acao="condicoes" aria-expanded="false">Ver condições completas</button>` : ""}
      <button type="button" class="pt-btn" data-acao="linha">Detalhe completo da linha</button>
      <button type="button" class="pt-btn" data-acao="transacoes" aria-expanded="false">Transações semelhantes</button>
    </div>
    ${detalhes}
    <div class="pt-painel" hidden></div>
  </article>`;
}

async function _renderTransacoesSemelhantes(container, filtros) {
  container.innerHTML = '<p class="meta">Buscando transações semelhantes...</p>';
  const params = { limit: 5, order_by: "valor", order_dir: "desc" };
  if (filtros.setor) params.setor = filtros.setor;
  if (filtros.porte) params.porte = filtros.porte;
  if (filtros.agencia) params.agencia = filtros.agencia;
  if (filtros.volume > 0) {
    // mesma ordem de grandeza (metade a 2x), nao o valor exato
    params.valor_min = Math.round(filtros.volume * 0.5);
    params.valor_max = Math.round(filtros.volume * 2);
  }
  let ops;
  try {
    ops = await fetchJSON("/api/operacoes?" + qs(params));
  } catch (e) {
    container.innerHTML = '<p class="meta">Não foi possível carregar transações semelhantes agora.</p>';
    return;
  }
  if (!Array.isArray(ops) || !ops.length) {
    container.innerHTML = '<p class="meta">Nenhuma transação semelhante na base para esse perfil.</p>';
    return;
  }
  container.innerHTML = `<p class="meta" style="margin:0 0 6px;">Referências históricas da base (não garantem aprovação nem as mesmas condições).</p>
    <table class="ops-table"><thead><tr><th>Cliente</th><th>Agência</th><th>Setor</th><th>Valor</th></tr></thead><tbody>
    ${ops.map((op) => `<tr data-id="${esc(op.id)}" tabindex="0" style="cursor:pointer;">
      <td>${esc(op.cliente || "-")}</td><td>${esc(op.agencia || "-")}</td>
      <td>${esc(op.setor_bndes || "Não classificado")}</td><td>${fmtBRLFull(op.valor_contratado)}</td></tr>`).join("")}
    </tbody></table>`;
  container.querySelectorAll("tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", () => openOperacaoDetalhe(tr.dataset.id));
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") openOperacaoDetalhe(tr.dataset.id); });
  });
}

function _ptLigarCards(box, linhasPorId, perfil) {
  box.addEventListener("click", async (e) => {
    const btn = e.target.closest(".pt-btn[data-acao]");
    if (!btn) return;
    const card = btn.closest(".pt-card");
    const l = linhasPorId[card?.dataset.id];
    if (!l) return;
    const acao = btn.dataset.acao;
    if (acao === "linha") { openLinhaDetalhe(l.id); return; }
    if (acao === "condicoes") {
      const dl = card.querySelector(".pt-detalhes");
      const abrir = dl.hidden;
      dl.hidden = !abrir;
      btn.setAttribute("aria-expanded", String(abrir));
      btn.textContent = abrir ? "Ocultar condições" : "Ver condições completas";
      return;
    }
    if (acao === "transacoes") {
      const painel = card.querySelector(".pt-painel");
      const abrir = painel.hidden;
      painel.hidden = !abrir;
      btn.setAttribute("aria-expanded", String(abrir));
      if (abrir && !painel.dataset.carregado) {
        painel.dataset.carregado = "1";
        const SETORES_BNDES = ["AGROPECUÁRIA", "COMERCIO/SERVICOS", "INDUSTRIA", "INFRAESTRUTURA"];
        const AGENCIAS_COM_OPERACOES = ["BNDES", "FINEP", "BNB"];
        await _renderTransacoesSemelhantes(painel, {
          setor: SETORES_BNDES.includes(l.setor_padronizado) ? l.setor_padronizado : perfil.setor,
          porte: perfil.porte,
          volume: perfil.volume,
          agencia: AGENCIAS_COM_OPERACOES.includes(l.instituicao) ? l.instituicao : undefined,
        });
      }
    }
  });
}

function _ptResumoExclusoes(data) {
  const descartadas = (data.total_candidatos || 0) - (data.total_compativeis || 0);
  if (descartadas <= 0) return "";
  const motivos = (data.exclusoes || []).map((x) => `${x.motivo.toLowerCase()} (${x.n})`).join(", ");
  return ` · ${fmtNum(descartadas)} descartadas por regra de elegibilidade${motivos ? ": " + esc(motivos) : ""}`;
}

async function _buscarPotenciais() {
  const erroEl = document.getElementById("pt-erro");
  const volumeEl = document.getElementById("pt-f-volume");
  const box = document.getElementById("pt-resultado");
  erroEl.hidden = true;
  volumeEl.removeAttribute("aria-invalid");
  const form = _ptForm();
  sincronizarFiltrosNaURL(form);

  const volumeMM = _ptParseValorMM(form.volume);
  if (Number.isNaN(volumeMM)) {
    erroEl.textContent = "Informe o valor em R$ milhões, maior que zero (ex.: 2,5).";
    erroEl.hidden = false;
    volumeEl.setAttribute("aria-invalid", "true");
    return;
  }
  if (!form.atividade && !form.finalidade && !form.porte && volumeMM === null) {
    _ptRenderVazio();
    return;
  }

  const params = {};
  ["atividade", "finalidade", "tomador", "porte", "uf"].forEach((k) => { if (form[k]) params[k] = form[k]; });
  if (volumeMM) params.volume = volumeMM * 1_000_000;

  const token = (_buscarPotenciais._token = (_buscarPotenciais._token || 0) + 1);
  box.setAttribute("aria-busy", "true");
  box.innerHTML = '<div class="pt-lista"><div class="pt-skel"></div><div class="pt-skel"></div><div class="pt-skel"></div></div>';
  let data;
  try {
    data = await fetchJSON("/api/potenciais/buscar?" + qs(params));
  } catch (e) {
    if (token !== _buscarPotenciais._token) return;
    box.removeAttribute("aria-busy");
    box.innerHTML = '<p class="pt-vazio">Erro ao buscar linhas. Tente novamente.</p>';
    return;
  }
  if (token !== _buscarPotenciais._token) return;
  box.removeAttribute("aria-busy");

  if (!data || data.erro) {
    erroEl.textContent = (data && data.erro) || "Erro ao buscar linhas.";
    erroEl.hidden = false;
    box.innerHTML = "";
    return;
  }

  const principais = data.resultados || [];
  const outras = data.outras_opcoes || [];
  const perfil = Object.assign({}, data.perfil || {}, { setor: (data.perfil || {}).setor || _ptSetorPorAtividade[form.atividade] });
  const linhasPorId = {};
  principais.concat(outras).forEach((l) => { linhasPorId[l.id] = l; });

  let html = `<p class="pt-resumo">${principais.length ? `${fmtNum(principais.length)} linha(s) com potencial aderência` : "Nenhuma linha com aderência média ou alta"}${_ptResumoExclusoes(data)}.</p>`;
  if (principais.length) {
    html += `<div class="pt-lista">${principais.map(_ptCard).join("")}</div>`;
  } else {
    html += '<p class="pt-vazio">Nenhuma linha do catálogo atende a todos os critérios informados. Tente ampliar o perfil (ex.: deixar a finalidade ou o valor em branco).</p>';
  }
  if (outras.length) {
    html += `<details class="pt-outras"${principais.length ? "" : " open"}><summary>Outras opções, com aderência baixa (${fmtNum(outras.length)})</summary>
      <div class="pt-lista">${outras.map(_ptCard).join("")}</div></details>`;
  }
  box.innerHTML = html;
  const novo = box.cloneNode(true); // remove listeners de buscas anteriores
  box.replaceWith(novo);
  _ptLigarCards(novo, linhasPorId, perfil);
}

document.addEventListener("DOMContentLoaded", () => {
  const buscarDebounced = debounce(_buscarPotenciais, 300);
  document.getElementById("pt-buscar-btn")?.addEventListener("click", _buscarPotenciais);
  document.getElementById("pt-limpar-btn")?.addEventListener("click", () => {
    Object.entries(_PT_CAMPOS).forEach(([chave, id]) => {
      const el = document.getElementById(id);
      if (el) el.value = chave === "tomador" ? "empresa" : "";
    });
    document.getElementById("pt-erro").hidden = true;
    sincronizarFiltrosNaURL({});
    _ptRenderVazio();
  });
  Object.values(_PT_CAMPOS).forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener(el.tagName === "SELECT" ? "change" : "input", buscarDebounced);
    if (el.tagName === "INPUT") el.addEventListener("keydown", (e) => { if (e.key === "Enter") _buscarPotenciais(); });
  });
  _initPotenciaisOpcoes();
});
