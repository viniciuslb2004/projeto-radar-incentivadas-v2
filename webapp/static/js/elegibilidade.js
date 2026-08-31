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
  if (!elegEditaisAtuais.length) {
    return `<div class="detalhe-secao">
      <div class="detalhe-secao-titulo">Editais abertos para os quais sua empresa pode se candidatar</div>
      <div style="padding:14px;"><p class="empty-state" style="padding:0;">Nenhum edital aberto para empresas no momento.</p></div>
    </div>`;
  }
  return `<div class="detalhe-secao">
    <div class="detalhe-secao-titulo">Editais abertos para os quais sua empresa pode se candidatar (${fmtNum(editais.total)})</div>
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
    html += `<table class="ops-table"><thead><tr><th>Cliente</th><th>Agência</th><th>UF</th><th>Data</th><th>Valor contratado</th></tr></thead><tbody>`;
    op.exemplos.forEach((e) => {
      html += `<tr><td>${e.cliente || "-"}</td><td>${e.agencia}</td><td>${e.uf || "-"}</td><td>${e.data_contratacao || "-"}</td><td>${fmtBRLFull(e.valor_contratado)}</td></tr>`;
    });
    html += `</tbody></table>`;
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
function linhasEnquadraveisHTML(linhas) {
  if (!linhas || !linhas.length) return "";
  return `<div class="detalhe-secao">
    <div class="detalhe-secao-titulo">Linhas de crédito possivelmente enquadráveis <span style="font-weight:400; text-transform:none; color:var(--blue-lighter);">sem prazo -- não dependem de edital aberto</span></div>
    <div style="padding:14px;">
      <p class="hint" style="margin:0 0 10px;">Linhas permanentes do BNDES/FINEP mais usadas por empresas do mesmo setor/porte -- vale procurar um agente financeiro ou o site oficial para ver as condições atuais de cada uma.</p>
      <table class="ops-table"><thead><tr><th>Linha</th><th>Operações no setor</th><th>Valor médio</th></tr></thead><tbody>
        ${linhas.map((l) => `<tr><td>${l.produto}</td><td>${fmtNum(l.n_operacoes)}</td><td>${fmtBRLFull(l.valor_medio)}</td></tr>`).join("")}
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

  let html = '<div class="detalhe-secoes">';
  html += empresaCardHTML(data.empresa);
  html += setorCardHTML(data.setor_mapeado);
  html += renderEditaisElegiveis(data.editais);
  html += operacoesParecidasHTML(data.operacoes_parecidas);
  html += linhasEnquadraveisHTML(data.operacoes_parecidas.linhas_enquadraveis);
  html += "</div>";
  container.innerHTML = html;

  container.querySelectorAll(".edital-card").forEach((card) => {
    card.addEventListener("click", () => openEditalDetalhe(card.dataset.id));
  });
  const btnExportar = document.getElementById("eleg-exportar-editais-btn");
  if (btnExportar) btnExportar.addEventListener("click", exportarElegEditaisCSV);
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("eleg-consultar-btn").addEventListener("click", consultarElegibilidade);
  document.getElementById("eleg-cnpj-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") consultarElegibilidade();
  });
});
