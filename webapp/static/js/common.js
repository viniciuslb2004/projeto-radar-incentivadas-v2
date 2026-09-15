// Utilidades compartilhadas: filtros, formatacao, tabs, modal de drill-down.

const AZUL_TONS = ["#223850", "#2E4A68", "#36587E", "#5878A0", "#7C93AC", "#A9BAC9", "#D3DCE3"];

function fmtBRL(v) {
  if (v === null || v === undefined || isNaN(v)) return "-";
  if (Math.abs(v) >= 1e9) return "R$ " + (v / 1e9).toFixed(1).replace(".", ",") + " bi";
  if (Math.abs(v) >= 1e6) return "R$ " + (v / 1e6).toFixed(1).replace(".", ",") + " mi";
  if (Math.abs(v) >= 1e3) return "R$ " + (v / 1e3).toFixed(0) + " mil";
  return "R$ " + Math.round(v);
}

function fmtBRLFull(v) {
  if (v === null || v === undefined) return "-";
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
}

function fmtNum(v) {
  if (v === null || v === undefined) return "-";
  return v.toLocaleString("pt-BR");
}

// Quando o frontend e o backend estao hospedados em dominios separados (ex:
// frontend na Vercel, backend no Render), API_BASE_URL (definida em config.js)
// aponta pro backend; localmente fica "" (mesma origem, como sempre).
function _urlCompleta(url) {
  if (url.startsWith("/api/") && window.API_BASE_URL) {
    return window.API_BASE_URL.replace(/\/$/, "") + url;
  }
  return url;
}

// Sem ISSO por padrao, uma chamada sem timeoutMs explicito nunca resolvia nem
// rejeitava se o backend travasse/nao respondesse (ex: cold-start do free tier do
// Render meio truncado por algum motivo) -- o await ficava pendurado pra sempre.
// Isso ja travou a pagina inteira de verdade: initFiltersAndTabs() (ver mais
// abaixo) so registra os cliques das abas DEPOIS do fetch de /api/status, entao um
// fetch sem timeout que nunca resolve deixa ate a NAVEGACAO entre abas travada,
// nao so o dado que ficaria faltando. 45s cobre com folga o cold-start do Render;
// chamadas que legitimamente demoram mais ja passam o proprio timeoutMs mais longo
// explicitamente, entao nao sao afetadas.
const TIMEOUT_PADRAO_MS = 45000;

// ============ Login (tela custom, ver #login-overlay em index.html) ============
// Ate 2026-09: HTTP Basic + header guardado em sessionStorage. Substituido por
// sessao de cookie (conta individual, tabela `admin_usuarios`, EXCECAO documentada
// a segregacao do painel /admin -- ver webapp/admin/auth.py e CLAUDE.md, secao
// "Painel de Admin"). O cookie e httponly (JS nunca le/escreve ele diretamente) e
// enviado automaticamente pelo navegador via `credentials: "include"` -- por isso
// fetchJSON/postJSON abaixo nao precisam mais montar nenhum header de Authorization.
class ErroAutenticacao extends Error {}

async function fetchJSON(url, timeoutMs) {
  const fullUrl = _urlCompleta(url);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs || TIMEOUT_PADRAO_MS);
  try {
    const r = await fetch(fullUrl, { signal: controller.signal, credentials: "include" });
    if (r.status === 401) throw new ErroAutenticacao("nao autenticado");
    return await r.json();
  } finally {
    clearTimeout(timer);
  }
}

// POST generico (usado, por exemplo, para mandar ao servidor o vetor de embedding
// ja calculado no navegador, no modo hospedado -- ver embeddings-client.js).
async function postJSON(url, body, timeoutMs) {
  const fullUrl = _urlCompleta(url);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs || TIMEOUT_PADRAO_MS);
  try {
    const r = await fetch(fullUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      credentials: "include",
      signal: controller.signal,
    });
    if (r.status === 401) throw new ErroAutenticacao("nao autenticado");
    return await r.json();
  } finally {
    clearTimeout(timer);
  }
}

// DELETE/PATCH genericos (mesmo padrao/timeout/tratamento de 401 de fetchJSON/
// postJSON acima) -- usados pelas rotas de Transacoes Salvas (ver salvos.js).
async function deleteJSON(url, timeoutMs) {
  const fullUrl = _urlCompleta(url);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs || TIMEOUT_PADRAO_MS);
  try {
    const r = await fetch(fullUrl, { method: "DELETE", credentials: "include", signal: controller.signal });
    if (r.status === 401) throw new ErroAutenticacao("nao autenticado");
    return await r.json();
  } finally {
    clearTimeout(timer);
  }
}

async function patchJSON(url, body, timeoutMs) {
  const fullUrl = _urlCompleta(url);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs || TIMEOUT_PADRAO_MS);
  try {
    const r = await fetch(fullUrl, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      credentials: "include",
      signal: controller.signal,
    });
    if (r.status === 401) throw new ErroAutenticacao("nao autenticado");
    return await r.json();
  } finally {
    clearTimeout(timer);
  }
}

function _mostrarLoginOverlay(mensagemErro) {
  document.getElementById("login-overlay").classList.remove("hidden");
  const erro = document.getElementById("login-erro");
  if (mensagemErro) {
    erro.textContent = mensagemErro;
    erro.classList.remove("hidden");
  } else {
    erro.classList.add("hidden");
  }
  document.getElementById("login-usuario").focus();
}

// POST /api/login com as credenciais digitadas -- em caso de sucesso, o backend ja
// devolve o cookie de sessao (Set-Cookie), nada pra guardar manualmente aqui.
async function _tentarLogin(usuario, senha) {
  try {
    const r = await fetch(_urlCompleta("/api/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: usuario, password: senha }),
      credentials: "include",
    });
    return r.status === 200;
  } catch (e) {
    // erro de rede tratado como falha de login tambem -- usuario ve a mesma
    // mensagem e pode tentar de novo.
    return false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("login-card").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("login-btn");
    btn.disabled = true;
    btn.textContent = "Entrando...";
    const usuario = document.getElementById("login-usuario").value;
    const senha = document.getElementById("login-senha").value;
    const ok = await _tentarLogin(usuario, senha);
    btn.disabled = false;
    btn.textContent = "Entrar";
    if (ok) {
      // Recarrega a pagina inteira em vez de tentar re-disparar manualmente a
      // inicializacao de cada aba (consolidado.js, tendencias.js etc, cada um so
      // roda seu proprio DOMContentLoaded uma vez) -- mais simples e robusto:
      // com o header ja guardado, o proximo /api/status já passa direto.
      location.reload();
    } else {
      document.getElementById("login-senha").value = "";
      _mostrarLoginOverlay("Usuário ou senha incorretos.");
    }
  });

  // Nome do usuario logado + botao Sair no canto da topbar (so aparece quando o
  // login por conta individual estiver configurado E alguem estiver logado --
  // ver /api/me em webapp/main.py). Sem login configurado (dev local sem nenhuma
  // conta ainda), a rota devolve username=null e este bloco fica escondido.
  fetch(_urlCompleta("/api/me"), { credentials: "include" })
    .then((r) => (r.ok ? r.json() : { username: null }))
    .then((dado) => {
      if (!dado.username) return;
      document.getElementById("topbar-usuario-nome").textContent = dado.username;
      document.getElementById("topbar-usuario").classList.remove("hidden");
    })
    .catch(() => {});

  document.getElementById("topbar-logout-btn").addEventListener("click", async () => {
    try {
      await fetch(_urlCompleta("/api/logout"), { method: "POST", credentials: "include" });
    } catch (e) {
      // segue pro reload mesmo assim -- o pior caso e o cookie continuar valido
      // ate expirar sozinho (24h), sem travar o usuario na tela.
    }
    location.reload();
  });
});

// Exporta uma lista de objetos como CSV (abre direto no Excel/Sheets) -- so client-side,
// sem ida ao servidor, pra funcionar igual no modo local e no hospedado. `colunas` e uma
// lista de {chave, rotulo}; `rotulo` vira o cabecalho, `chave` busca o valor em cada linha
// (aceita "a.b" para acessar aninhado, embora nenhum uso atual precise disso).
function exportarCSV(nomeArquivo, linhas, colunas) {
  const escapar = (valor) => {
    if (valor === null || valor === undefined) return "";
    const texto = String(valor);
    return /[",\n;]/.test(texto) ? '"' + texto.replace(/"/g, '""') + '"' : texto;
  };
  const cabecalho = colunas.map((c) => escapar(c.rotulo)).join(";");
  const corpo = linhas
    .map((linha) => colunas.map((c) => escapar(linha[c.chave])).join(";"))
    .join("\n");
  // BOM (﻿) pra o Excel abrir os acentos certo em UTF-8 sem precisar importar manualmente.
  const blob = new Blob(["﻿" + cabecalho + "\n" + corpo], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nomeArquivo;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

const MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];

function currentFilters() {
  const filters = {
    agencia: document.getElementById("f-agencia").value,
    setor: document.getElementById("f-setor").value,
    uf: document.getElementById("f-uf").value,
  };

  const mesIni = document.getElementById("f-mes-ini").value;
  const anoIni = document.getElementById("f-ano-ini").value;
  if (mesIni && anoIni) {
    filters.data_inicio = `${anoIni}-${String(mesIni).padStart(2, "0")}-01`;
  }

  const mesFim = document.getElementById("f-mes-fim").value;
  const anoFim = document.getElementById("f-ano-fim").value;
  if (mesFim && anoFim) {
    let m = parseInt(mesFim, 10) + 1;
    let y = parseInt(anoFim, 10);
    if (m > 12) { m = 1; y += 1; }
    filters.data_fim = `${y}-${String(m).padStart(2, "0")}-01`;
  }

  return filters;
}

function qs(params) {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "" && v !== "Todas" && v !== "Todos") p.set(k, v);
  });
  return p.toString();
}

const FILTER_LISTENERS = [];
function onFiltersChange(fn) { FILTER_LISTENERS.push(fn); }
function notifyFiltersChange() { FILTER_LISTENERS.forEach((fn) => fn(currentFilters())); }

// ============ Filtros na URL (query string) ============
// Cada aba reflete os PROPRIOS filtros na query string (nunca o path, que ja
// codifica qual aba esta aberta -- ver secao de roteamento logo abaixo), pra dar
// pra compartilhar um link que abre a mesma aba com os mesmos filtros aplicados.
// Usa SEMPRE replaceState (nunca pushState) pra nao poluir o historico de
// voltar/avancar do navegador a cada filtro alterado -- so a troca de ABA deve
// criar uma entrada de historico nova (ver _ativarView). Decisao deliberada e
// CONSERVADORA sobre o que entra na URL: so filtros que restringem QUAL FATIA dos
// dados aparece (setor, UF, agencia, data, texto de busca etc.). Qualquer coisa
// que so muda COMO os mesmos dados sao exibidos (granularidade do grafico de
// serie temporal -- ver #serie-granularidade, ja excluida explicitamente antes
// por pedido do usuario -- e tambem os selects de ORDENACAO em Editais/Linhas/
// Busca/modal de operacoes, e a pagina atual da paginacao de Linhas Incentivadas)
// fica de fora, tratada como estado local da pagina (mesmo padrao ja usado pra
// granularidade). Ambiguidade real: dava pra argumentar que ordenacao/pagina
// tambem deveriam entrar agora que a URL passou a carregar filtro -- decisao
// tomada foi NAO incluir (nenhum desses foi pedido explicitamente pra entrar na
// URL), pra manter escopo minimo e consistente com a exclusao ja definida da
// granularidade.
function paramsDaURL() {
  return new URLSearchParams(window.location.search);
}

// Cada aba lembra seu PROPRIO ultimo conjunto de filtros (nao herda de outra
// aba) -- mas Consolidado e Tendencias compartilham o mesmo #filterbar (mesmos
// elementos DOM fisicos, so escondido via display:none), entao sao tratados
// como um unico "grupo" (`painel`) pra esse fim: alternar entre os dois nunca
// deve limpar nada, ja que o filtro de um E o do outro (mesmo input). Busca,
// Editais e Linhas Incentivadas sao cada um o proprio grupo (filtros/conceitos
// de UI incompativeis entre si -- ex: Busca usa "regiao", Consolidado usa "uf").
// `_ultimaQueryPorGrupo` e um cache em memoria (nao sobrevive a um F5 de
// proposito -- um F5/link direto usa a query string ja presente na URL, ver
// `_aplicarFiltros*DaURL` de cada aba) que guarda, por grupo, a ultima query
// string sincronizada -- consultado por `_ativarView` (secao de roteamento
// abaixo) na hora de montar a URL de destino de um clique real numa aba. So
// precisa mexer na URL: os CAMPOS de filtro de cada aba ja preservam seu valor
// sozinhos ao trocar de aba (nenhum codigo os reseta quando a aba fica
// escondida), so a URL que ficava dessincronizada da tela.
const _ultimaQueryPorGrupo = {};
function _grupoDaView(view) {
  if (view === "consolidado" || view === "tendencias") return "painel";
  return view;
}

// Guarda qual aba esta ativa AGORA -- usado so pra `sincronizarFiltrosNaURL`
// saber em qual grupo gravar o cache acima (nao dá pra inferir isso so pelos
// `params` recebidos, que variam de aba pra aba).
let _viewAtivaAgora = null;

function sincronizarFiltrosNaURL(params) {
  const query = qs(params);
  const destino = window.location.pathname + (query ? "?" + query : "");
  if (destino !== window.location.pathname + window.location.search) {
    window.history.replaceState(window.history.state, "", destino);
  }
  if (_viewAtivaAgora) _ultimaQueryPorGrupo[_grupoDaView(_viewAtivaAgora)] = query;
}

// Debounce generico -- usado pelos campos de texto livre (query da Busca, texto da
// Editais, busca de Linhas Incentivadas) pra nao chamar sincronizarFiltrosNaURL a
// cada tecla digitada. O VALOR final ainda fica refletido na URL assim que o
// usuario para de digitar (`ms` depois da ultima tecla).
function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

// Roteamento por caminho: a URL reflete qual aba esta aberta (/consolidado,
// /tendencias, /busca, /editais, /linhas-incentivadas) via PATH -- os filtros de
// cada aba (ver secao acima) vao na query string do mesmo caminho.
const _SLUG_PARA_VIEW = {
  "": "consolidado",
  "consolidado": "consolidado",
  "tendencias": "tendencias",
  "busca": "busca",
  "editais": "editais",
  "linhas-incentivadas": "linhas",
  "transacoes-salvas": "salvos",
};
const _VIEW_PARA_SLUG = {
  consolidado: "consolidado",
  tendencias: "tendencias",
  busca: "busca",
  editais: "editais",
  linhas: "linhas-incentivadas",
  salvos: "transacoes-salvas",
};

function _viewInicialDaURL() {
  const slug = window.location.pathname.replace(/^\/+|\/+$/g, "");
  return _SLUG_PARA_VIEW[slug] || "consolidado";
}

function _ativarView(view, empilharHistorico) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
  document.getElementById("filterbar").style.display =
    view === "busca" || view === "editais" || view === "linhas" || view === "salvos" ? "none" : "flex";
  const caminho = "/" + (_VIEW_PARA_SLUG[view] || "consolidado");
  const mudouDeAba = window.location.pathname !== caminho;
  if (empilharHistorico) {
    // Clique numa aba: so cria uma entrada de historico nova se REALMENTE mudou
    // de aba (clicar na aba ja ativa nao deve limpar filtro nenhum). Ao mudar de
    // verdade, restaura o ULTIMO conjunto de filtros que o GRUPO da aba de
    // destino teve nesta mesma visita a pagina (`_ultimaQueryPorGrupo`) -- nunca
    // herda o da aba de ORIGEM, que pode ser de um grupo diferente (ver
    // `_grupoDaView`). Os campos de filtro em si nao precisam de nada aqui: ja
    // preservam seu valor sozinhos (nenhum reset ao trocar de aba), so a URL
    // que precisava voltar a bater com o que ja esta na tela.
    if (mudouDeAba) {
      const query = _ultimaQueryPorGrupo[_grupoDaView(view)] || "";
      window.history.pushState({ view }, "", caminho + (query ? "?" + query : ""));
    }
  } else if (mudouDeAba) {
    // Estado inicial (carregamento direto/F5) ou popstate (voltar/avancar):
    // preserva a query string como estava -- pode ser um link compartilhado com
    // filtros, ou uma entrada de historico anterior que ja tinha os seus.
    window.history.replaceState({ view }, "", caminho + window.location.search);
  }
  // Semeia o cache pro grupo desta aba a partir da URL atual, se ainda nao
  // tiver nada gravado -- cobre o caso de carregar a pagina direto (F5/link
  // compartilhado) numa aba com filtro na URL: sem isso, o cache so passaria a
  // existir depois da PRIMEIRA mudanca de filtro feita pelo usuario, entao
  // sair e voltar pra essa aba antes disso perderia a query que ja estava la.
  const grupo = _grupoDaView(view);
  if (_ultimaQueryPorGrupo[grupo] === undefined) {
    _ultimaQueryPorGrupo[grupo] = window.location.search.replace(/^\?/, "");
  }
  _viewAtivaAgora = view;
}

// Nao deixa o usuario chegar num intervalo invertido (De > Ate): sempre que um dos 4
// selects de data muda, compara os dois pares como "ano*12+mes" (comparavel direto,
// sem precisar montar Date) -- se o par que NAO acabou de mudar ficou invalido em
// relacao ao que mudou, ajusta ele pra igualar o que o usuario acabou de escolher
// (em vez de reverter a escolha do usuario ou so avisar sem corrigir). O aviso
// inline (#filtro-data-aviso, mesmo padrao visual de .confianca-baixa-aviso usado na
// busca) aparece por alguns segundos so quando uma correcao de verdade acontece.
function _ordemMesAno(mes, ano) {
  if (!mes || !ano) return null;
  return parseInt(ano, 10) * 12 + parseInt(mes, 10);
}

function validarIntervaloDatas(campoAlterado) {
  const mesIniEl = document.getElementById("f-mes-ini");
  const anoIniEl = document.getElementById("f-ano-ini");
  const mesFimEl = document.getElementById("f-mes-fim");
  const anoFimEl = document.getElementById("f-ano-fim");

  const ordemIni = _ordemMesAno(mesIniEl.value, anoIniEl.value);
  const ordemFim = _ordemMesAno(mesFimEl.value, anoFimEl.value);
  if (ordemIni === null || ordemFim === null || ordemIni <= ordemFim) return;

  // O campo que acabou de mudar manda -- o outro lado e que se ajusta pra igualar.
  const alterouInicio = campoAlterado === "f-mes-ini" || campoAlterado === "f-ano-ini";
  if (alterouInicio) {
    mesFimEl.value = mesIniEl.value;
    anoFimEl.value = anoIniEl.value;
  } else {
    mesIniEl.value = mesFimEl.value;
    anoIniEl.value = anoFimEl.value;
  }

  const aviso = document.getElementById("filtro-data-aviso");
  if (aviso) {
    aviso.style.display = "block";
    clearTimeout(aviso._timeoutId);
    aviso._timeoutId = setTimeout(() => { aviso.style.display = "none"; }, 4000);
  }
}

// Liga/desliga os degrades de borda de `.tabs-wrap` (ver style.css) conforme
// da pra rolar `.tabs` pra esquerda/direita NAQUELE momento -- a barra de
// scroll nativa foi escondida de proposito (feia em larguras de desktop
// intermediarias), entao esse e o unico aviso visual de que ha mais abas fora
// da tela. Chamada no carregamento, ao redimensionar a janela e a cada scroll
// dentro de `.tabs` (arrastar/roda do mouse muda quanto da pra rolar em cada
// direcao).
function _atualizarSombraAbas() {
  const wrap = document.getElementById("tabs-wrap");
  const tabs = document.getElementById("tabs");
  if (!wrap || !tabs) return;
  const folgaDireita = tabs.scrollWidth - tabs.clientWidth - tabs.scrollLeft;
  wrap.classList.toggle("tem-mais-a-esquerda", tabs.scrollLeft > 2);
  wrap.classList.toggle("tem-mais-a-direita", folgaDireita > 2);
}

function _ligarBotoesDeAba() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => _ativarView(btn.dataset.view, true));
  });
  window.addEventListener("popstate", () => _ativarView(_viewInicialDaURL(), false));
  _ativarView(_viewInicialDaURL(), false);

  const tabsEl = document.getElementById("tabs");
  if (tabsEl) tabsEl.addEventListener("scroll", _atualizarSombraAbas);
  window.addEventListener("resize", _atualizarSombraAbas);
  _atualizarSombraAbas();
}

// Esconde a tela de carregamento inicial -- chamada em TODO caminho de saida de
// initFiltersAndTabs() (sucesso ou erro), pra nunca deixar o usuario preso atras
// dela se o backend estiver fora do ar.
function _esconderLoadingOverlay() {
  const overlay = document.getElementById("loading-overlay");
  if (overlay) overlay.classList.add("hidden");
}

// Tendencias.js precisa dos valores do filterbar compartilhado (agencia/setor/
// UF/data, incluindo os que vieram de um link com filtro na URL -- ver
// initFiltersAndTabs abaixo) ja aplicados ANTES do seu proprio fetch inicial,
// mas quem chama initFiltersAndTabs() e so consolidado.js. Em vez de um
// setTimeout arbitrario torcendo pra initFiltersAndTabs() (que depende de
// /api/status + /api/filtros por rede) terminar a tempo -- flaky de verdade
// contra o Aiven free tier (ver CLAUDE.md) e que ja mostrou na pratica buscar
// com os filtros ainda default/vazios quando a rede demora mais que o palpite
// -- tendencias.js AGUARDA esta promise, resolvida no finally de
// initFiltersAndTabs() (sucesso ou erro, pra nunca travar esperando pra sempre).
let _resolverFiltrosProntos;
const filtrosProntosPromise = new Promise((resolve) => { _resolverFiltrosProntos = resolve; });

async function initFiltersAndTabs() {
  // Troca de aba e 100% client-side (so classes CSS) -- liga ISSO primeiro e
  // incondicionalmente, antes de qualquer fetch, pra a navegacao nunca depender
  // do backend responder.
  _ligarBotoesDeAba();

  try {
    await _initFiltersAndTabsImpl();
  } finally {
    _resolverFiltrosProntos();
  }
}

async function _initFiltersAndTabsImpl() {
  const pill = document.getElementById("status-pill");
  let status;
  try {
    status = await fetchJSON("/api/status");
  } catch (e) {
    _esconderLoadingOverlay();
    if (e instanceof ErroAutenticacao) {
      _mostrarLoginOverlay();
      return;
    }
    pill.textContent = "não foi possível conectar ao servidor";
    return;
  }
  window.MODO_HOSPEDADO = !!status.hospedado;
  window.BUSCA_IA_ATIVA = !!status.busca_ia_ativa;
  document.dispatchEvent(new CustomEvent("modo-hospedado-conhecido"));
  if (status.ultimo_refresh && status.ultimo_refresh.finished_at) {
    const d = new Date(status.ultimo_refresh.finished_at);
    pill.textContent = `${fmtNum(status.n_operacoes)} operações · atualizado em ${d.toLocaleDateString("pt-BR")}`;
  } else {
    pill.textContent = `${fmtNum(status.n_operacoes)} operações`;
  }

  let filtros;
  try {
    filtros = await fetchJSON("/api/filtros");
  } catch (e) {
    _esconderLoadingOverlay();
    return;
  }
  const fill = (id, values) => {
    const sel = document.getElementById(id);
    values.forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      sel.appendChild(opt);
    });
  };
  fill("f-agencia", filtros.agencias);
  fill("f-setor", filtros.setores.filter(Boolean));
  fill("f-uf", filtros.ufs.filter(Boolean));

  const anos = filtros.anos.filter((a) => a !== null).sort((a, b) => a - b);
  const anoIni = document.getElementById("f-ano-ini");
  const anoFim = document.getElementById("f-ano-fim");
  const mesIni = document.getElementById("f-mes-ini");
  const mesFim = document.getElementById("f-mes-fim");

  MESES.forEach((nome, i) => {
    mesIni.appendChild(new Option(nome, i + 1));
    mesFim.appendChild(new Option(nome, i + 1));
  });
  anos.forEach((a) => {
    anoIni.appendChild(new Option(a, a));
    anoFim.appendChild(new Option(a, a));
  });

  const dataMin = filtros.data_min ? new Date(filtros.data_min) : null;
  const dataMax = filtros.data_max ? new Date(filtros.data_max) : null;
  if (dataMin) {
    mesIni.value = dataMin.getUTCMonth() + 1;
    anoIni.value = dataMin.getUTCFullYear();
  } else if (anos.length) {
    anoIni.value = anos[0];
  }
  if (dataMax) {
    mesFim.value = dataMax.getUTCMonth() + 1;
    anoFim.value = dataMax.getUTCFullYear();
  } else if (anos.length) {
    anoFim.value = anos[anos.length - 1];
  }

  // Link compartilhado / F5: se a URL ja tem filtros (so relevante quando a aba
  // ativa e Consolidado ou Tendencias, que sao as duas que usam este filterbar
  // compartilhado -- ver _viewInicialDaURL), sobrescreve os valores padrao ACIMA
  // ANTES do primeiro fetch de cada aba (consolidado.js/tendencias.js so leem os
  // valores via currentFilters() depois que initFiltersAndTabs() retorna).
  const viewAtiva = _viewInicialDaURL();
  if (viewAtiva === "consolidado" || viewAtiva === "tendencias") {
    const paramsIniciais = paramsDaURL();
    if (paramsIniciais.has("agencia")) document.getElementById("f-agencia").value = paramsIniciais.get("agencia");
    if (paramsIniciais.has("setor")) document.getElementById("f-setor").value = paramsIniciais.get("setor");
    if (paramsIniciais.has("uf")) document.getElementById("f-uf").value = paramsIniciais.get("uf");
    if (paramsIniciais.has("mes_ini")) mesIni.value = paramsIniciais.get("mes_ini");
    if (paramsIniciais.has("ano_ini")) anoIni.value = paramsIniciais.get("ano_ini");
    if (paramsIniciais.has("mes_fim")) mesFim.value = paramsIniciais.get("mes_fim");
    if (paramsIniciais.has("ano_fim")) anoFim.value = paramsIniciais.get("ano_fim");
  }

  const CAMPOS_DATA = ["f-mes-ini", "f-ano-ini", "f-mes-fim", "f-ano-fim"];
  ["f-agencia", "f-setor", "f-uf", ...CAMPOS_DATA].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => {
      if (CAMPOS_DATA.includes(id)) validarIntervaloDatas(id);
      notifyFiltersChange();
      _sincronizarFiltrosCompartilhadosNaURL();
    });
  });

  _esconderLoadingOverlay();
}

// Filtros compartilhados por Consolidado e Tendencias (mesmo filterbar, ver
// #filterbar em index.html) -- granularidade do grafico de serie temporal
// (#serie-granularidade, fica dentro da secao visual do Consolidado) fica DE
// FORA de proposito, pedido explicito e anterior do usuario (ver "Filtros na
// URL" acima).
function _sincronizarFiltrosCompartilhadosNaURL() {
  sincronizarFiltrosNaURL({
    agencia: document.getElementById("f-agencia").value,
    setor: document.getElementById("f-setor").value,
    uf: document.getElementById("f-uf").value,
    mes_ini: document.getElementById("f-mes-ini").value,
    ano_ini: document.getElementById("f-ano-ini").value,
    mes_fim: document.getElementById("f-mes-fim").value,
    ano_fim: document.getElementById("f-ano-fim").value,
  });
}

// ============ Modal de drill-down ============
const modalOverlay = () => document.getElementById("modal-overlay");

function closeModal() {
  modalOverlay().classList.remove("open");
}

let modalExtraFilters = {};

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("modal-close").addEventListener("click", closeModal);
  modalOverlay().addEventListener("click", (e) => {
    if (e.target === modalOverlay()) closeModal();
  });
  document.getElementById("modal-ordenar").addEventListener("change", () => {
    openOperacoesModal(document.getElementById("modal-title").textContent, modalExtraFilters, true);
  });
});

async function openOperacoesModal(title, extraFilters, manterOrdenacao) {
  if (!manterOrdenacao) modalExtraFilters = extraFilters || {};
  document.getElementById("modal-title").textContent = title;
  const body = document.getElementById("modal-body");
  const ordenarSelect = document.getElementById("modal-ordenar");
  ordenarSelect.style.display = "inline-block";
  document.getElementById("modal-favoritar-btn").style.display = "none";
  body.innerHTML = '<p class="empty-state">Carregando...</p>';
  modalOverlay().classList.add("open");

  const [order_by, order_dir] = ordenarSelect.value.split("-");
  const params = Object.assign(currentFilters(), modalExtraFilters, { order_by, order_dir });
  const ops = await fetchJSON("/api/operacoes?" + qs(params) + "&limit=300");

  if (!ops.length) {
    body.innerHTML = '<p class="empty-state">Nenhuma operação encontrada para esse filtro.</p>';
    return;
  }

  let html = '<table class="ops-table"><thead><tr>' +
    "<th>Cliente</th><th>Agência</th><th>UF</th><th>Setor</th><th>Data</th><th>Valor contratado</th>" +
    "</tr></thead><tbody>";
  ops.forEach((op) => {
    html += `<tr data-id="${op.id}">
      <td>${op.cliente || "-"}</td>
      <td>${op.agencia}</td>
      <td>${op.uf || "-"}</td>
      <td>${op.setor_bndes || "Não classificado"}</td>
      <td>${op.data_contratacao || "-"}</td>
      <td>${fmtBRLFull(op.valor_contratado)}</td>
    </tr>`;
  });
  html += "</tbody></table>";
  body.innerHTML = html;

  body.querySelectorAll("tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", () => openOperacaoDetalhe(tr.dataset.id));
  });
}

function fmtCampoDetalhe(campo) {
  const v = campo.valor;
  switch (campo.tipo) {
    case "moeda":
      return fmtBRLFull(v);
    case "percentual":
      return `${Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 2 })}%`;
    case "meses":
      return `${v} meses`;
    case "dias":
      return `${v} dias`;
    case "data":
      return v;
    default:
      return String(v).trim();
  }
}

// Botao "Salvar"/"★ Salvo" do modal de detalhe de operacao (Transacoes Salvas, ver
// webapp/salvos.py) -- reutilizavel de qualquer lugar que abre esse mesmo modal
// (busca, tabela de operacoes, grupo economico etc, ja que todos passam por
// openOperacaoDetalhe). Escondido por padrao (ver #modal-favoritar-btn em
// index.html); os outros abridores de modal (openOperacoesModal, editais.js,
// linhas.js) escondem de novo explicitamente, ja que reusam o MESMO elemento.
function _configurarBotaoFavoritar(opId, salva) {
  const btn = document.getElementById("modal-favoritar-btn");
  if (!btn) return;
  btn.style.display = "inline-flex";
  const atualizarEstado = (ativo) => {
    btn.textContent = ativo ? "★ Salvo" : "☆ Salvar";
    btn.classList.toggle("ativo", ativo);
  };
  atualizarEstado(!!salva);
  btn.onclick = async () => {
    btn.disabled = true;
    try {
      if (btn.classList.contains("ativo")) {
        await deleteJSON(`/api/salvos/operacoes/${opId}`);
        atualizarEstado(false);
      } else {
        await postJSON(`/api/salvos/operacoes/${opId}`, {});
        atualizarEstado(true);
      }
      // Se a aba Transacoes Salvas ja carregou nesta visita, atualiza a lista dela
      // tambem -- funcao exposta por salvos.js, so chamada se existir.
      if (typeof recarregarSalvos === "function") recarregarSalvos();
    } catch (e) {
      alert(e instanceof ErroAutenticacao ? "Faça login para salvar operações." : "Não foi possível atualizar o favorito agora.");
    } finally {
      btn.disabled = false;
    }
  };
}

async function openOperacaoDetalhe(id) {
  document.getElementById("modal-title").textContent = "Detalhe da operação";
  document.getElementById("modal-ordenar").style.display = "none";
  const body = document.getElementById("modal-body");
  body.innerHTML = '<p class="empty-state">Carregando...</p>';
  modalOverlay().classList.add("open");

  const data = await fetchJSON(`/api/operacoes/${id}`);
  if (!data.secoes || !data.secoes.length) {
    body.innerHTML = '<p class="empty-state">Detalhe não encontrado.</p>';
    return;
  }

  const badge = `<span class="badge" style="background:var(--blue-lightest); color:var(--navy); margin-left:8px;">${data.agencia}${data.instrumento ? " · " + data.instrumento : ""}</span>`;
  document.getElementById("modal-title").innerHTML = `Detalhe da operação ${badge}`;
  _configurarBotaoFavoritar(id, data.salva);

  let html = '<div class="detalhe-secoes">';
  data.secoes.forEach((secao) => {
    const textoLongo = secao.campos.find((c) => c.tipo === "texto_longo");
    const camposCurtos = secao.campos.filter((c) => c.tipo !== "texto_longo");

    html += `<div class="detalhe-secao">
      <div class="detalhe-secao-titulo">${secao.titulo}</div>`;

    if (camposCurtos.length) {
      html += '<div class="detalhe-grid">';
      camposCurtos.forEach((c) => {
        html += `<div class="detalhe-campo">
          <div class="detalhe-label">${c.label}</div>
          <div class="detalhe-valor">${fmtCampoDetalhe(c)}</div>
        </div>`;
      });
      html += "</div>";
    }
    if (textoLongo) {
      html += `<div class="detalhe-texto-longo">${fmtCampoDetalhe(textoLongo)}</div>`;
    }
    html += "</div>";
  });
  html += "</div>";
  body.innerHTML = html;

  // Integracao transacoes <-> linhas incentivadas (item 8): mesma logica do lado
  // inverso em linhas.js -- so setor_bndes (taxonomia nativa das 4 categorias),
  // rotulado "potencialmente compativel", nunca misturado com o detalhe da operacao.
  if (data.setor_bndes && typeof fetchJSON === "function") {
    try {
      const linhas = await fetchJSON("/api/linhas?" + qs({ setor: data.setor_bndes, limit: 3 }));
      if (linhas.resultados && linhas.resultados.length) {
        const div = document.createElement("div");
        div.className = "detalhe-secao";
        div.innerHTML = `<div class="detalhe-secao-titulo">Linhas incentivadas potencialmente compatíveis <span class="hint">mesmo setor -- não é confirmação de elegibilidade</span></div>` +
          '<ul class="clickable-list">' +
          linhas.resultados.map((l) => `<li data-linha-id="${l.id}"><span>${l.nome_simplificado || l.nome_oficial}</span><span class="badge neutro">${l.instituicao}</span></li>`).join("") +
          "</ul>";
        body.appendChild(div);
        div.querySelectorAll("li[data-linha-id]").forEach((li) => {
          li.addEventListener("click", () => {
            if (typeof openLinhaDetalhe === "function") openLinhaDetalhe(li.dataset.linhaId);
          });
        });
      }
    } catch (e) {
      // integracao e um extra -- se falhar, so nao mostra a secao.
    }
  }

  // Grupo economico (mesma raiz de CNPJ, matriz+filiais) -- mesmo padrao da secao de
  // linhas compativeis acima: carregada a parte, so aparece se houver resultado, nunca
  // bloqueia o resto do detalhe se falhar.
  try {
    const grupo = await fetchJSON(`/api/operacoes/${id}/grupo-economico`);
    if (grupo.resultados && grupo.resultados.length) {
      const div = document.createElement("div");
      div.className = "detalhe-secao";
      div.innerHTML = `<div class="detalhe-secao-titulo">Outras operações do mesmo grupo econômico (${grupo.resultados.length}) <span class="hint">mesma raiz de CNPJ</span></div>` +
        '<ul class="clickable-list">' +
        grupo.resultados.map((o) => `<li data-op-id="${o.id}"><span>${o.cliente}</span><span class="badge neutro">${o.agencia} · ${fmtBRL(o.valor_contratado)}</span></li>`).join("") +
        "</ul>";
      body.appendChild(div);
      div.querySelectorAll("li[data-op-id]").forEach((li) => {
        li.addEventListener("click", () => openOperacaoDetalhe(li.dataset.opId));
      });
    }
  } catch (e) {
    // integracao e um extra -- se falhar, so nao mostra a secao.
  }
}
