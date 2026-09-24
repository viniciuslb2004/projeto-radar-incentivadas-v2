// Aba "Potenciais Linhas" (item 3 do pedido): usuario informa caracteristicas do
// projeto (setor, porte, volume, uso dos recursos) e recebe um ranking de Linhas
// Incentivadas com "potencial aderência" -- NUNCA "elegibilidade confirmada" (ver
// texto no card de cada resultado). Motor de recomendacao 100% determinístico
// (filtros + score por regras, ver webapp/potenciais.py), sem IA/chamada a
// modelo. "Transações Semelhantes" (item 4) reaproveita /api/operacoes (mesma
// rota que Consolidado/Busca/modal ja usam), sem rota nova.

let potenciaisOpcoesCarregadas = false;

// Campo "UF da empresa" (gap-fix 2026-09-23 -- item 3 do pedido: filtro
// geografico pra diferenciar linhas de bancos regionais como BASA/BNB/
// Desenvolve SP das linhas nacionais BNDES/FINEP). Escopo desta tarefa e SO
// webapp/potenciais.py + este arquivo -- index.html pertence a outra area de
// edicao, entao o campo e criado via DOM em vez de editar o HTML estatico
// (mesmo container .filterbar que ja tem Setor/Subsetor/Porte/Volume/Uso).
function _garantirCampoUf() {
  if (document.getElementById("pt-f-uf")) return;
  const setorWrapper = document.getElementById("pt-f-setor")?.closest("div");
  const filterbar = setorWrapper?.parentElement;
  if (!filterbar) return;
  const wrapper = document.createElement("div");
  wrapper.innerHTML =
    '<label for="pt-f-uf">UF da empresa <span class="hint">(opcional, prioriza/filtra linhas regionais como BASA, BNB e Desenvolve SP)</span></label>' +
    '<select id="pt-f-uf" aria-label="UF da empresa"><option value="">Todo o Brasil</option></select>';
  filterbar.appendChild(wrapper);
}

async function _initPotenciaisOpcoes() {
  if (potenciaisOpcoesCarregadas) return;
  _garantirCampoUf();
  let opcoes;
  try {
    opcoes = await fetchJSON("/api/potenciais/opcoes");
  } catch (e) {
    return; // selects ficam so com a opcao padrao -- nao trava o resto da aba
  }
  const fill = (id, values, manterPrimeira) => {
    const sel = document.getElementById(id);
    if (!sel) return;
    (values || []).forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      sel.appendChild(opt);
    });
  };
  fill("pt-f-setor", opcoes.setores || []);
  fill("pt-f-subsetor", opcoes.subsetores || []);
  fill("pt-f-porte", opcoes.portes || []);
  fill("pt-f-uso", opcoes.usos || []);
  fill("pt-f-uf", opcoes.ufs || []);
  potenciaisOpcoesCarregadas = true;
  _aplicarFiltrosPotenciaisDaURL();
}

// Restaura o formulario a partir da URL (F5/link compartilhado) DEPOIS que as
// opcoes dos selects existem, e ja dispara a busca se houver algum criterio --
// nenhum request extra alem do que o proprio clique em "Buscar" faria.
const _CAMPOS_POTENCIAIS_URL = { setor: "pt-f-setor", subsetor: "pt-f-subsetor", porte: "pt-f-porte", volume: "pt-f-volume", uso: "pt-f-uso", uf: "pt-f-uf" };
function _aplicarFiltrosPotenciaisDaURL() {
  if (_viewInicialDaURL() !== "potenciais") return;
  const params = paramsDaURL();
  let algum = false;
  Object.entries(_CAMPOS_POTENCIAIS_URL).forEach(([chave, id]) => {
    const el = document.getElementById(id);
    if (el && params.has(chave)) { el.value = params.get(chave); algum = algum || !!el.value; }
  });
  if (algum) _buscarPotenciais();
}

function _potenciaisFormAtual() {
  return {
    setor: document.getElementById("pt-f-setor").value,
    subsetor: document.getElementById("pt-f-subsetor").value,
    porte: document.getElementById("pt-f-porte").value,
    // Valor digitado pelo usuario em R$ MM (item 3 do gap-fix 2026-09-22, campo
    // "Valor desejado (R$ MM)" em index.html) -- ainda em MM aqui, string bruta
    // do <input>. A conversao pra reais cheios (x 1_000_000) e a validacao
    // acontecem em _buscarPotenciais, ANTES de montar os parametros pra API e
    // ANTES de qualquer uso deste mesmo objeto `form` mais abaixo (inclusive
    // "Transações Semelhantes", que reusa `form` via closure) -- backend
    // (webapp/potenciais.py) e valor_minimo/valor_maximo de linhas_incentivadas
    // continuam em reais cheios, sem nenhuma mudanca de schema/contrato.
    volume: document.getElementById("pt-f-volume").value,
    uso: document.getElementById("pt-f-uso").value,
    // UF da empresa (gap-fix 2026-09-23): campo criado via _garantirCampoUf,
    // pode nao existir ainda na primeira renderizacao -- optional chaining.
    uf: document.getElementById("pt-f-uf")?.value || "",
  };
}

function _rotuloParaClasseBadge(rotulo) {
  if (rotulo === "Alta") return "up";
  if (rotulo === "Baixa") return "down";
  return "neutro";
}

// "Transações Semelhantes" (item 4 do pedido): busca comparaveis reais em
// `operations` reaproveitando /api/operacoes (ja estendido com os filtros
// porte/valor_min/valor_max, ver webapp/main.py::_filters_clause) -- nenhuma
// logica de query nova aqui, so montagem dos parametros. Mostra so um preview
// pequeno (5 linhas) inline, "não inundar a tela" (item 4), nunca a lista
// inteira sem o usuario pedir.
async function _renderTransacoesSemelhantes(containerId, filtrosForm) {
  const container = document.getElementById(containerId);
  container.innerHTML = '<p class="empty-state">Buscando transações semelhantes...</p>';

  const params = {};
  if (filtrosForm.setor) params.setor = filtrosForm.setor;
  if (filtrosForm.subsetor) params.subsetor = filtrosForm.subsetor;
  if (filtrosForm.porte) params.porte = filtrosForm.porte;
  // Instituicao (item 5 do gap-fix 2026-09-22): so quando o CHAMADOR ja
  // confirmou que a instituicao da linha e uma das poucas que `operations.agencia`
  // de fato cobre (ver AGENCIAS_COM_OPERACOES_REAIS mais abaixo, no unico lugar
  // que chama esta funcao com uma linha especifica) -- restricao conhecida
  // (CLAUDE.md/webapp/potenciais.py): operations.agencia SO tem 'BNDES'/'FINEP',
  // a base de transacoes reais nao cobre BNB/Desenvolve SP/BASA/BB/CEF. Nunca
  // inventa um valor de agencia quando a linha e de outra instituicao -- so
  // filtra quando ha dado real (mesmo texto) pra usar.
  if (filtrosForm.agencia) params.agencia = filtrosForm.agencia;
  if (filtrosForm.volume) {
    // Faixa em torno do volume informado (metade a 2x) -- comparaveis "na mesma
    // ordem de grandeza", nao so operacoes com o valor EXATO (quase nunca bate).
    const v = Number(filtrosForm.volume);
    if (v > 0) {
      params.valor_min = Math.round(v * 0.5);
      params.valor_max = Math.round(v * 2);
    }
  }
  params.limit = 5;
  params.order_by = "valor";
  params.order_dir = "desc";

  let ops;
  try {
    ops = await fetchJSON("/api/operacoes?" + qs(params));
  } catch (e) {
    container.innerHTML = '<p class="empty-state">Não foi possível carregar transações semelhantes agora.</p>';
    return;
  }

  if (!Array.isArray(ops) || !ops.length) {
    container.innerHTML = '<p class="empty-state">Nenhuma transação semelhante encontrada na base para esses critérios.</p>';
    return;
  }

  let html = '<p class="meta" style="margin-bottom:8px;">Referências históricas da base deste app -- não é garantia de aprovação nem das mesmas condições no futuro.</p>';
  html += '<table class="ops-table"><thead><tr><th>Cliente</th><th>Agência</th><th>Setor</th><th>Valor contratado</th></tr></thead><tbody>';
  ops.forEach((op) => {
    html += `<tr data-id="${esc(op.id)}" style="cursor:pointer;">
      <td>${esc(op.cliente || "-")}</td>
      <td>${esc(op.agencia || "-")}</td>
      <td>${esc(op.setor_bndes || "Não classificado")}</td>
      <td>${fmtBRLFull(op.valor_contratado)}</td>
    </tr>`;
  });
  html += "</tbody></table>";
  container.innerHTML = html;
  container.querySelectorAll("tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", () => openOperacaoDetalhe(tr.dataset.id));
  });
}

function _potenciaisCard(linha, formAtual) {
  const badgeClasse = _rotuloParaClasseBadge(linha.score_rotulo);
  const motivosHtml = (linha.motivos || []).map((m) => `<li>${esc(m)}</li>`).join("");
  const transacoesId = `pt-transacoes-${esc(linha.id)}`;
  const naoInf = (v) => esc(v && v !== "Não informado pela fonte" ? v : "Não informado");
  return `<div class="result-card" data-id="${esc(linha.id)}" style="cursor:default;">
    <div class="top-row">
      <span class="cliente">${esc(linha.nome)}</span>
      <span>
        <span class="badge neutro">${esc(linha.instituicao)}</span>
        <span class="badge ${badgeClasse}">Potencial aderência: ${esc(linha.score_rotulo)} (${esc(linha.score_pct)}%)</span>
      </span>
    </div>
    <div class="kpi-row" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); margin:10px 0;">
      <div class="kpi-card"><div class="label">Taxa</div><div class="value" style="font-size:15px;">${naoInf(linha.taxa_completa)}</div></div>
      <div class="kpi-card"><div class="label">Prazo</div><div class="value" style="font-size:15px;">${naoInf(linha.prazo_total)}</div></div>
      <div class="kpi-card"><div class="label">Carência</div><div class="value" style="font-size:15px;">${naoInf(linha.carencia)}</div></div>
      <div class="kpi-card"><div class="label">Limite de participação</div><div class="value" style="font-size:15px;">${naoInf(linha.percentual_financiavel)}</div></div>
    </div>
    <div class="meta"><strong>Por que faz sentido:</strong></div>
    <ul class="meta" style="margin:4px 0 8px 18px;">${motivosHtml || "<li>Nenhum critério em comum informado.</li>"}</ul>
    <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:8px;">
      <button class="acao-btn" id="pt-ver-linha-${esc(linha.id)}">Ver detalhe completo da linha</button>
      <button class="acao-btn" id="pt-ver-transacoes-${esc(linha.id)}">Ver transações semelhantes</button>
    </div>
    <div id="${transacoesId}" style="display:none; margin-top:10px;"></div>
  </div>`;
}

async function _buscarPotenciais() {
  const erroEl = document.getElementById("pt-erro");
  erroEl.style.display = "none";
  const form = _potenciaisFormAtual();
  // URL reflete o formulario da busca efetivamente disparada (volume ainda em
  // R$ MM, como digitado) -- ver secao "Filtros na URL" em common.js.
  sincronizarFiltrosNaURL(form);

  if (!form.setor && !form.porte && !form.volume && !form.uso) {
    erroEl.textContent = "Informe ao menos um critério (setor, porte, volume ou uso dos recursos).";
    erroEl.style.display = "block";
    return;
  }

  // Valor desejado em R$ MM -> reais cheios (item 3), com validacao simples
  // contra entrada absurda (0/negativo) -- muta `form.volume` no lugar pra que
  // TODO uso posterior deste mesmo objeto (params abaixo e "Transações
  // Semelhantes" via closure no forEach mais abaixo) ja receba o valor em reais.
  if (form.volume) {
    const volumeMM = Number(form.volume);
    if (!Number.isFinite(volumeMM) || volumeMM <= 0) {
      erroEl.textContent = "Informe um valor desejado válido em R$ MM (maior que zero).";
      erroEl.style.display = "block";
      return;
    }
    form.volume = volumeMM * 1_000_000;
  }

  const lista = document.getElementById("pt-lista");
  const contagem = document.getElementById("pt-contagem");
  lista.innerHTML = '<p class="empty-state">Buscando linhas potenciais...</p>';
  contagem.textContent = "";

  const params = {};
  if (form.setor) params.setor = form.setor;
  if (form.porte) params.porte = form.porte;
  if (form.volume) params.volume = form.volume;
  if (form.uso) params.uso = form.uso;
  if (form.uf) params.uf = form.uf;
  // Subsetor (gap-fix 2026-09-23): so entra como sinal ADICIONAL de correlacao
  // textual dentro do criterio de setor (ver webapp/potenciais.py::
  // _correlacao_textual_setor) -- nunca um filtro estrutural novo, continua
  // sem contar pro "informe ao menos um critério" do backend.
  if (form.subsetor) params.subsetor = form.subsetor;

  const token = (_buscarPotenciais._token = (_buscarPotenciais._token || 0) + 1);
  const btnBuscar = document.getElementById("pt-buscar-btn");
  let data;
  try {
    if (btnBuscar) btnBuscar.disabled = true;
    data = await fetchJSON("/api/potenciais/buscar?" + qs(params));
  } catch (e) {
    if (token !== _buscarPotenciais._token) return;
    lista.innerHTML = '<p class="empty-state">Erro ao buscar linhas potenciais. Tente novamente.</p>';
    return;
  } finally {
    if (btnBuscar && token === _buscarPotenciais._token) btnBuscar.disabled = false;
  }
  if (token !== _buscarPotenciais._token) return; // busca mais nova ja disparada

  if (!data || data.erro) {
    if (!data) { lista.innerHTML = '<p class="empty-state">Erro ao buscar linhas potenciais. Tente novamente.</p>'; return; }
    erroEl.textContent = data.erro;
    erroEl.style.display = "block";
    lista.innerHTML = "";
    return;
  }

  if (!data.resultados || !data.resultados.length) {
    lista.innerHTML = '<p class="empty-state">Nenhuma linha incentivada com aderência avaliável para esses critérios.</p>';
    return;
  }

  contagem.textContent = `${data.resultados.length} linha(s) potencial(is) encontrada(s) (de ${fmtNum(data.total_candidatos || 0)} candidatas avaliadas)`;
  lista.innerHTML = data.resultados.map((l) => _potenciaisCard(l, form)).join("");

  data.resultados.forEach((l) => {
    const btnLinha = document.getElementById(`pt-ver-linha-${l.id}`);
    if (btnLinha) btnLinha.addEventListener("click", () => openLinhaDetalhe(l.id));

    const btnTransacoes = document.getElementById(`pt-ver-transacoes-${l.id}`);
    const painel = document.getElementById(`pt-transacoes-${l.id}`);
    if (btnTransacoes && painel) {
      btnTransacoes.addEventListener("click", async () => {
        const abrindo = painel.style.display === "none";
        painel.style.display = abrindo ? "block" : "none";
        if (abrindo && !painel.dataset.carregado) {
          painel.dataset.carregado = "1";
          // Setor da PROPRIA linha (quando na taxonomia BNDES) tem prioridade
          // sobre o setor generico do formulario -- comparavel mais preciso pra
          // esta linha especifica. Ver mesma taxonomia em linhas.js.
          const SETORES_TAXONOMIA_BNDES = ["AGROPECUÁRIA", "COMERCIO/SERVICOS", "INDUSTRIA", "INFRAESTRUTURA"];
          // Instituicao (item 5): so passa agencia quando a instituicao da
          // PROPRIA linha e uma das que `operations.agencia` realmente cobre --
          // nunca inventa o filtro pra BNB/Desenvolve SP/BASA/BB/CEF (a base de
          // transacoes reais nao tem essas instituicoes, ver restricao no topo
          // deste arquivo/CLAUDE.md).
          const AGENCIAS_COM_OPERACOES_REAIS = ["BNDES", "FINEP", "BNB"];
          const formComSetorDaLinha = Object.assign({}, form, {
            setor: SETORES_TAXONOMIA_BNDES.includes(l.setor_padronizado) ? l.setor_padronizado : form.setor,
            agencia: AGENCIAS_COM_OPERACOES_REAIS.includes(l.instituicao) ? l.instituicao : undefined,
          });
          await _renderTransacoesSemelhantes(`pt-transacoes-${l.id}`, formComSetorDaLinha);
        }
      });
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("pt-buscar-btn");
  if (btn) btn.addEventListener("click", _buscarPotenciais);
  // Opcoes so precisam ser buscadas 1x -- carrega incondicional no boot (mesmo
  // padrao ja usado por linhas.js/editais.js pra funcionar com URL direta/F5,
  // sem depender de clique na aba).
  _initPotenciaisOpcoes();
});
