// Aba "Minha Empresa": o usuario digita o CNPJ da PROPRIA empresa (nao um CNPJ que ja
// esta na base) e o sistema resolve setor/porte via BrasilAPI (ver /api/elegibilidade,
// que chama src/elegibilidade.py) para mostrar editais abertos aplicaveis e como
// empresas do mesmo setor/porte se sairam historicamente com credito BNDES/FINEP.
// Reaproveita editalCardHTML/openEditalDetalhe (editais.js) para nao duplicar o card
// do edital nem o modal de detalhe.

let elegEditaisAtuais = [];

function fmtCNPJExibicao(cnpj) {
  if (!cnpj || cnpj.length !== 14) return cnpj || "-";
  return `${cnpj.slice(0, 2)}.${cnpj.slice(2, 5)}.${cnpj.slice(5, 8)}/${cnpj.slice(8, 12)}-${cnpj.slice(12, 14)}`;
}

function empresaCardHTML(empresa) {
  const situacaoBadge = empresa.situacao_cadastral
    ? `<span class="badge ${empresa.situacao_cadastral_alerta ? "down" : "up"}" style="margin-left:8px;">${empresa.situacao_cadastral}</span>`
    : "";
  return `<div class="detalhe-secao">
    <div class="detalhe-secao-titulo">Dados da empresa</div>
    <div class="detalhe-grid">
      <div class="detalhe-campo"><div class="detalhe-label">Razão social</div><div class="detalhe-valor">${empresa.razao_social || "-"}${situacaoBadge}</div></div>
      <div class="detalhe-campo"><div class="detalhe-label">Nome fantasia</div><div class="detalhe-valor">${empresa.nome_fantasia || "-"}</div></div>
      <div class="detalhe-campo"><div class="detalhe-label">CNPJ</div><div class="detalhe-valor">${fmtCNPJExibicao(empresa.cnpj)}</div></div>
      <div class="detalhe-campo"><div class="detalhe-label">CNAE principal</div><div class="detalhe-valor">${empresa.cnae_codigo || "-"}${empresa.cnae_descricao ? " - " + empresa.cnae_descricao : ""}</div></div>
      <div class="detalhe-campo"><div class="detalhe-label">UF / Município</div><div class="detalhe-valor">${empresa.uf || "-"}${empresa.municipio ? " · " + empresa.municipio : ""}</div></div>
      <div class="detalhe-campo"><div class="detalhe-label">Porte (Receita Federal)</div><div class="detalhe-valor">${empresa.porte_receita || "Não informado"}</div></div>
    </div>
  </div>`;
}

function setorCardHTML(setorMapeado) {
  if (!setorMapeado.mapeado) {
    return `<div class="detalhe-secao">
      <div class="detalhe-secao-titulo">Setor BNDES/FINEP</div>
      <div style="padding:14px;"><p class="empty-state" style="padding:0;">Não conseguimos identificar automaticamente o setor BNDES/FINEP desta empresa a partir do CNAE dela. Os editais abertos para empresas em geral ainda aparecem abaixo, mas não foi possível comparar com o histórico de operações por setor.</p></div>
    </div>`;
  }
  return `<div class="detalhe-secao">
    <div class="detalhe-secao-titulo">Setor BNDES/FINEP <span style="font-weight:400; text-transform:none; color:var(--blue-lighter);">estimado a partir do CNAE</span></div>
    <div class="detalhe-grid">
      <div class="detalhe-campo"><div class="detalhe-label">Setor</div><div class="detalhe-valor">${setorMapeado.setor_bndes}</div></div>
      <div class="detalhe-campo"><div class="detalhe-label">Subsetor</div><div class="detalhe-valor">${setorMapeado.subsetor_bndes || "-"}</div></div>
      ${setorMapeado.porte_bndes_equivalente ? `<div class="detalhe-campo"><div class="detalhe-label">Porte equivalente (BNDES)</div><div class="detalhe-valor">${setorMapeado.porte_bndes_equivalente}</div></div>` : ""}
    </div>
  </div>`;
}

function renderEditaisElegiveis(editais) {
  elegEditaisAtuais = editais.resultados || [];
  const subtitulo = editais.ranqueado_por_ia
    ? "ordenados por IA pelo que mais tem a ver com o que sua empresa faz"
    : "todos os editais abertos aplicáveis a empresas";
  if (!elegEditaisAtuais.length) {
    return `<div class="detalhe-secao">
      <div class="detalhe-secao-titulo">Editais abertos para os quais sua empresa pode se candidatar</div>
      <div style="padding:14px;"><p class="empty-state" style="padding:0;">Nenhum edital aberto para empresas no momento.</p></div>
    </div>`;
  }
  return `<div class="detalhe-secao">
    <div class="detalhe-secao-titulo">Editais abertos para os quais sua empresa pode se candidatar (${fmtNum(editais.total)}) <span style="font-weight:400; text-transform:none; color:var(--blue-lighter);">${subtitulo}</span></div>
    <div style="padding:14px;">
      <button class="header-select" id="eleg-exportar-editais-btn" style="cursor:pointer; margin-bottom:10px; background:var(--navy); color:#fff; border-color:var(--navy);">Exportar CSV</button>
      <div id="eleg-editais-lista">${elegEditaisAtuais.map(editalCardHTML).join("")}</div>
    </div>
  </div>`;
}

function operacoesParecidasHTML(op) {
  if (!op.total) {
    return `<div class="detalhe-secao">
      <div class="detalhe-secao-titulo">Como empresas parecidas se saíram</div>
      <div style="padding:14px;"><p class="empty-state" style="padding:0;">Não encontramos operações históricas de BNDES/FINEP para empresas do mesmo setor${op.porte_considerado_no_filtro ? " e porte" : ""}.</p></div>
    </div>`;
  }
  const porAgenciaTxt = op.por_agencia.map((a) => `${a.agencia}: ${fmtNum(a.n_operacoes)} operações, ${fmtBRL(a.valor_total)}`).join(" · ");
  let html = `<div class="detalhe-secao">
    <div class="detalhe-secao-titulo">Como empresas parecidas se saíram <span style="font-weight:400; text-transform:none; color:var(--blue-lighter);">mesmo setor${op.porte_considerado_no_filtro ? " e porte" : ""}</span></div>
    <div style="padding:14px;">
      <div class="kpi-row" style="margin-bottom:14px;">
        ${kpiCard("Operações encontradas", fmtNum(op.total))}
        ${kpiCard("Valor médio por operação", fmtBRLFull(op.valor_medio))}
        ${kpiCard("Volume total contratado", fmtBRL(op.valor_total), porAgenciaTxt)}
      </div>`;
  if (op.exemplos && op.exemplos.length) {
    html += `<table class="ops-table" id="eleg-exemplos-tabela"><thead><tr><th>Cliente</th><th>Agência</th><th>UF</th><th>Data</th><th>Valor contratado</th></tr></thead><tbody>`;
    op.exemplos.forEach((e) => {
      html += `<tr data-id="${e.id}"><td>${e.cliente || "-"}</td><td>${e.agencia}</td><td>${e.uf || "-"}</td><td>${e.data_contratacao || "-"}</td><td>${fmtBRLFull(e.valor_contratado)}</td></tr>`;
    });
    html += `</tbody></table><p class="hint" style="margin:8px 0 0;">Clique em uma operação para ver todos os detalhes.</p>`;
  }
  if (!op.porte_considerado_no_filtro) {
    html += `<p style="margin-top:10px; font-size:12px; color:var(--text-muted);">Estes números consideram todas as empresas do setor, sem filtrar por porte (não foi possível equiparar o porte informado pela Receita Federal às categorias do BNDES para esta empresa).</p>`;
  }
  html += `</div></div>`;
  return html;
}

// Diferente de operacoesParecidasHTML (o que JA foi financiado -- olhando pro
// passado) e de renderEditaisElegiveis (chamadas com prazo -- podem fechar): isto
// mostra as LINHAS DE CREDITO PERMANENTES (sem prazo de validade) mais usadas por
// empresas do mesmo perfil, como um "isso aqui pode valer a pena tentar mesmo sem
// nenhum edital aberto agora".
function fmtMeses(v) {
  if (v === null || v === undefined) return "-";
  return `${Math.round(v)} meses`;
}

function fmtTaxa(v) {
  if (v === null || v === undefined) return "-";
  return `${v.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}% a.a.`;
}

// Cada linha da tabela principal é um resumo; clicar nela expande uma 2a linha logo
// abaixo com as condições reais (prazo de carência/amortização, taxa, indexador) --
// só existem pra produtos BNDES (ver comentário no backend), então quando tudo vem
// nulo (produto FINEP) a linha expandida avisa isso em vez de mostrar zeros.
function linhasEnquadraveisHTML(linhas) {
  if (!linhas || !linhas.length) return "";
  const linhasHTML = linhas
    .map((l, i) => {
      const semCondicoes = l.prazo_carencia_meses == null && l.prazo_amortizacao_meses == null && l.taxa_juros == null;
      const detalheHTML = semCondicoes
        ? `<p class="empty-state" style="padding:0;">Condições detalhadas (prazo/taxa) não disponíveis para esta linha -- consulte o agente financeiro ou o site oficial.</p>`
        : `<div class="detalhe-grid">
            <div class="detalhe-campo"><div class="detalhe-label">Carência</div><div class="detalhe-valor">${fmtMeses(l.prazo_carencia_meses)}</div></div>
            <div class="detalhe-campo"><div class="detalhe-label">Amortização</div><div class="detalhe-valor">${fmtMeses(l.prazo_amortizacao_meses)}</div></div>
            <div class="detalhe-campo"><div class="detalhe-label">Taxa de juros média</div><div class="detalhe-valor">${fmtTaxa(l.taxa_juros)}</div></div>
            <div class="detalhe-campo"><div class="detalhe-label">Indexador mais comum</div><div class="detalhe-valor">${l.indexador || "-"}</div></div>
          </div>`;
      return `<tr class="eleg-linha-row" data-linha-idx="${i}"><td>${l.produto}</td><td>${fmtNum(l.n_operacoes)}</td><td>${fmtBRLFull(l.valor_medio)}</td></tr>
        <tr class="eleg-linha-detalhe" data-linha-idx="${i}" style="display:none;"><td colspan="3" style="background:var(--blue-lightest);">${detalheHTML}</td></tr>`;
    })
    .join("");
  return `<div class="detalhe-secao">
    <div class="detalhe-secao-titulo">Linhas de crédito possivelmente enquadráveis <span style="font-weight:400; text-transform:none; color:var(--blue-lighter);">sem prazo -- não dependem de edital aberto</span></div>
    <div style="padding:14px;">
      <p class="hint" style="margin:0 0 10px;">Linhas permanentes do BNDES/FINEP mais usadas por empresas do mesmo setor/porte -- clique em uma linha para ver as condições médias (prazo, taxa, indexador). Vale sempre confirmar as condições atuais com um agente financeiro ou o site oficial.</p>
      <table class="ops-table" id="eleg-linhas-tabela"><thead><tr><th>Linha</th><th>Operações no setor</th><th>Valor médio</th></tr></thead><tbody>
        ${linhasHTML}
      </tbody></table>
    </div>
  </div>`;
}

function exportarElegEditaisCSV() {
  exportarCSV("editais_elegiveis.csv", elegEditaisAtuais, [
    { chave: "titulo", rotulo: "Título" },
    { chave: "tema_principal", rotulo: "Tema" },
    { chave: "tipo_oportunidade", rotulo: "Tipo de oportunidade" },
    { chave: "regiao", rotulo: "Região" },
    { chave: "prazo_proposto", rotulo: "Prazo de submissão" },
  ]);
}

async function consultarElegibilidade() {
  const input = document.getElementById("eleg-cnpj-input");
  const cnpj = input.value.trim();
  const container = document.getElementById("eleg-resultado");
  if (!cnpj) return;

  container.innerHTML = '<p class="empty-state">Consultando...</p>';
  let data;
  try {
    // BrasilAPI as vezes demora alguns segundos -- timeout um pouco mais folgado que o padrao.
    data = await fetchJSON("/api/elegibilidade?" + qs({ cnpj }), 20000);
  } catch (e) {
    container.innerHTML = '<p class="empty-state">Não foi possível consultar agora. Tente novamente.</p>';
    return;
  }

  if (data.erro) {
    container.innerHTML = `<p class="empty-state">${data.erro}</p>`;
    return;
  }

  // Ordem: dados da empresa -> setor -> o que já foi financiado (histórico) -> linhas
  // permanentes que dá pra tentar mesmo sem edital ativo -> por último, os editais
  // COM PRAZO (chamadas que podem fechar) -- pedido explícito do usuário: editais é
  // informação "urgente mas efêmera", enquanto as linhas de crédito são a resposta
  // mais direta e duradoura pra "o que posso fazer com essa empresa".
  let html = '<div class="detalhe-secoes">';
  html += empresaCardHTML(data.empresa);
  html += setorCardHTML(data.setor_mapeado);
  html += operacoesParecidasHTML(data.operacoes_parecidas);
  html += linhasEnquadraveisHTML(data.operacoes_parecidas.linhas_enquadraveis);
  html += renderEditaisElegiveis(data.editais);
  html += "</div>";
  container.innerHTML = html;

  container.querySelectorAll(".edital-card").forEach((card) => {
    card.addEventListener("click", () => openEditalDetalhe(card.dataset.id));
  });
  const btnExportar = document.getElementById("eleg-exportar-editais-btn");
  if (btnExportar) btnExportar.addEventListener("click", exportarElegEditaisCSV);

  container.querySelectorAll("#eleg-exemplos-tabela tbody tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", () => openOperacaoDetalhe(tr.dataset.id));
  });
  container.querySelectorAll("#eleg-linhas-tabela .eleg-linha-row").forEach((tr) => {
    tr.addEventListener("click", () => {
      const detalhe = container.querySelector(`.eleg-linha-detalhe[data-linha-idx="${tr.dataset.linhaIdx}"]`);
      if (detalhe) detalhe.style.display = detalhe.style.display === "none" ? "" : "none";
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("eleg-consultar-btn").addEventListener("click", consultarElegibilidade);
  document.getElementById("eleg-cnpj-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") consultarElegibilidade();
  });
});
