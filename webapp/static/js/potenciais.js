// Aba "Potenciais Linhas" (item 3 do pedido): usuario informa caracteristicas do
// projeto (setor, porte, volume, uso dos recursos) e recebe um ranking de Linhas
// Incentivadas com "potencial aderência" -- NUNCA "elegibilidade confirmada" (ver
// texto no card de cada resultado). Motor de recomendacao 100% determinístico
// (filtros + score por regras, ver webapp/potenciais.py), sem IA/chamada a
// modelo. "Transações Semelhantes" (item 4) reaproveita /api/operacoes (mesma
// rota que Consolidado/Busca/modal ja usam), sem rota nova.

let potenciaisOpcoesCarregadas = false;

async function _initPotenciaisOpcoes() {
  if (potenciaisOpcoesCarregadas) return;
  let opcoes;
  try {
    opcoes = await fetchJSON("/api/potenciais/opcoes");
  } catch (e) {
    return; // selects ficam so com a opcao padrao -- nao trava o resto da aba
  }
  const fill = (id, values, manterPrimeira) => {
    const sel = document.getElementById(id);
    if (!sel) return;
    values.forEach((v) => {
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
  potenciaisOpcoesCarregadas = true;
}

function _potenciaisFormAtual() {
  return {
    setor: document.getElementById("pt-f-setor").value,
    subsetor: document.getElementById("pt-f-subsetor").value,
    porte: document.getElementById("pt-f-porte").value,
    volume: document.getElementById("pt-f-volume").value,
    uso: document.getElementById("pt-f-uso").value,
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
    html += `<tr data-id="${op.id}" style="cursor:pointer;">
      <td>${op.cliente || "-"}</td>
      <td>${op.agencia || "-"}</td>
      <td>${op.setor_bndes || "Não classificado"}</td>
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
  const motivosHtml = (linha.motivos || []).map((m) => `<li>${m}</li>`).join("");
  const transacoesId = `pt-transacoes-${linha.id}`;
  return `<div class="result-card" data-id="${linha.id}" style="cursor:default;">
    <div class="top-row">
      <span class="cliente">${linha.nome}</span>
      <span>
        <span class="badge neutro">${linha.instituicao}</span>
        <span class="badge ${badgeClasse}">Potencial aderência: ${linha.score_rotulo} (${linha.score_pct}%)</span>
      </span>
    </div>
    <div class="kpi-row" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); margin:10px 0;">
      <div class="kpi-card"><div class="label">Taxa</div><div class="value" style="font-size:15px;">${linha.taxa_completa && linha.taxa_completa !== "Não informado pela fonte" ? linha.taxa_completa : "Não informado"}</div></div>
      <div class="kpi-card"><div class="label">Prazo</div><div class="value" style="font-size:15px;">${linha.prazo_total && linha.prazo_total !== "Não informado pela fonte" ? linha.prazo_total : "Não informado"}</div></div>
      <div class="kpi-card"><div class="label">Carência</div><div class="value" style="font-size:15px;">${linha.carencia && linha.carencia !== "Não informado pela fonte" ? linha.carencia : "Não informado"}</div></div>
      <div class="kpi-card"><div class="label">Limite de participação</div><div class="value" style="font-size:15px;">${linha.percentual_financiavel && linha.percentual_financiavel !== "Não informado pela fonte" ? linha.percentual_financiavel : "Não informado"}</div></div>
    </div>
    <div class="meta"><strong>Por que faz sentido:</strong></div>
    <ul class="meta" style="margin:4px 0 8px 18px;">${motivosHtml || "<li>Nenhum critério em comum informado.</li>"}</ul>
    <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:8px;">
      <button class="acao-btn" id="pt-ver-linha-${linha.id}">Ver detalhe completo da linha</button>
      <button class="acao-btn" id="pt-ver-transacoes-${linha.id}">Ver transações semelhantes</button>
    </div>
    <div id="${transacoesId}" style="display:none; margin-top:10px;"></div>
  </div>`;
}

async function _buscarPotenciais() {
  const erroEl = document.getElementById("pt-erro");
  erroEl.style.display = "none";
  const form = _potenciaisFormAtual();

  if (!form.setor && !form.porte && !form.volume && !form.uso) {
    erroEl.textContent = "Informe ao menos um critério (setor, porte, volume ou uso dos recursos).";
    erroEl.style.display = "block";
    return;
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

  let data;
  try {
    data = await fetchJSON("/api/potenciais/buscar?" + qs(params));
  } catch (e) {
    lista.innerHTML = '<p class="empty-state">Erro ao buscar linhas potenciais. Tente novamente.</p>';
    return;
  }

  if (data.erro) {
    erroEl.textContent = data.erro;
    erroEl.style.display = "block";
    lista.innerHTML = "";
    return;
  }

  if (!data.resultados || !data.resultados.length) {
    lista.innerHTML = '<p class="empty-state">Nenhuma linha incentivada com aderência avaliável para esses critérios.</p>';
    return;
  }

  contagem.textContent = `${data.resultados.length} linha(s) potencial(is) encontrada(s) (de ${data.total_candidatos} candidatas avaliadas)`;
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
          const formComSetorDaLinha = Object.assign({}, form, {
            setor: SETORES_TAXONOMIA_BNDES.includes(l.setor_padronizado) ? l.setor_padronizado : form.setor,
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
