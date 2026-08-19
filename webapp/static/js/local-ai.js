// IA local do visitante -- so entra em acao quando o backend esta em modo
// hospedado (MODO_HOSPEDADO, setado em common.js a partir de /api/status).
//
// No modo hospedado nao ha Ollama nenhum rodando no servidor (o servidor so
// prepara os prompts e guarda o cache compartilhado dos resumos de edital) --
// quem efetivamente gera o texto e o Ollama que a PESSOA tem instalado na
// propria maquina, chamado diretamente pelo navegador dela.

const OLLAMA_LOCAL_URL = "http://localhost:11434";
const OLLAMA_MODELO_PADRAO = "llama3.2:3b-instruct-q4_K_M";

let _ollamaDisponivel = null; // null = ainda nao verificado nesta sessao

async function verificarOllamaLocal(timeoutMs = 2000) {
  if (_ollamaDisponivel !== null) return _ollamaDisponivel;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const r = await fetch(`${OLLAMA_LOCAL_URL}/api/tags`, { signal: controller.signal });
    clearTimeout(timer);
    _ollamaDisponivel = r.ok;
  } catch (e) {
    _ollamaDisponivel = false;
  }
  return _ollamaDisponivel;
}

function resetarVerificacaoOllama() {
  _ollamaDisponivel = null;
}

// Gera texto via o Ollama local do visitante. `opcoes` pode ter {temperature, format}.
async function gerarComOllamaLocal(prompt, modelo, opcoes, timeoutMs = 240000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const body = {
      model: modelo || OLLAMA_MODELO_PADRAO,
      prompt,
      stream: false,
      options: { temperature: opcoes && opcoes.temperature !== undefined ? opcoes.temperature : 0.2 },
    };
    if (opcoes && opcoes.format) body.format = opcoes.format;

    const r = await fetch(`${OLLAMA_LOCAL_URL}/api/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!r.ok) throw new Error(`Ollama respondeu ${r.status}`);
    const data = await r.json();
    return (data.response || "").trim();
  } finally {
    clearTimeout(timer);
  }
}

// ============ Badge + modal "baixar IA local" ============

async function atualizarBadgeIALocal() {
  const badge = document.getElementById("ia-local-badge");
  if (!badge) return;
  badge.style.display = "inline-block";
  const disponivel = await verificarOllamaLocal();
  if (disponivel) {
    badge.textContent = "✓ IA local ativa";
    badge.className = "ia-local-badge ativa";
    badge.onclick = null;
    badge.style.cursor = "default";
  } else {
    badge.textContent = "Baixar IA local";
    badge.className = "ia-local-badge inativa";
    badge.style.cursor = "pointer";
    badge.onclick = abrirModalIALocal;
  }
}

function abrirModalIALocal() {
  const origem = window.location.origin;
  const overlay = document.getElementById("ia-local-modal-overlay");
  if (!overlay) return;

  // O link do script precisa apontar pro backend certo -- localmente e a
  // mesma origem da pagina, mas no deploy hospedado o frontend (Vercel) e o
  // backend (Render) ficam em dominios separados, entao usamos a mesma regra
  // de API_BASE_URL que o resto do app ja usa (ver common.js/_urlCompleta).
  const linkScript = document.getElementById("ia-local-script-link");
  if (linkScript && typeof _urlCompleta === "function") {
    linkScript.href = _urlCompleta("/api/config/instalar-ia.ps1");
  }

  // Fallback manual (instrucoes antigas, para quem preferir nao rodar o
  // script baixado ou estiver em Mac/Linux) continua disponivel, so
  // escondido por padrao -- ver <details> no index.html.
  document.getElementById("ia-local-comando-origens").textContent =
    `setx OLLAMA_ORIGINS "${origem}"`;
  document.getElementById("ia-local-comando-mac-linux").textContent =
    `OLLAMA_ORIGINS="${origem}" ollama serve`;
  document.getElementById("ia-local-comando-modelo").textContent =
    `ollama pull ${OLLAMA_MODELO_PADRAO}`;

  overlay.classList.add("open");
}

function fecharModalIALocal() {
  const overlay = document.getElementById("ia-local-modal-overlay");
  if (overlay) overlay.classList.remove("open");
}

async function verificarNovamenteIALocal() {
  const btn = document.getElementById("ia-local-verificar-btn");
  if (btn) { btn.disabled = true; btn.textContent = "Verificando..."; }
  resetarVerificacaoOllama();
  const disponivel = await verificarOllamaLocal();
  if (btn) { btn.disabled = false; btn.textContent = "Verificar novamente"; }
  await atualizarBadgeIALocal();
  if (disponivel) fecharModalIALocal();
}

function iniciarMonitorIALocal() {
  atualizarBadgeIALocal();
  setInterval(() => {
    resetarVerificacaoOllama();
    atualizarBadgeIALocal();
  }, 20000);
}

document.addEventListener("DOMContentLoaded", () => {
  document.addEventListener("modo-hospedado-conhecido", () => {
    if (window.MODO_HOSPEDADO) iniciarMonitorIALocal();
  });

  const closeBtn = document.getElementById("ia-local-modal-close");
  if (closeBtn) closeBtn.addEventListener("click", fecharModalIALocal);
  const verificarBtn = document.getElementById("ia-local-verificar-btn");
  if (verificarBtn) verificarBtn.addEventListener("click", verificarNovamenteIALocal);
  const overlay = document.getElementById("ia-local-modal-overlay");
  if (overlay) overlay.addEventListener("click", (e) => { if (e.target === overlay) fecharModalIALocal(); });

  document.querySelectorAll(".copiar-comando-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const alvo = document.getElementById(btn.dataset.alvo);
      if (!alvo) return;
      navigator.clipboard.writeText(alvo.textContent).then(() => {
        const original = btn.textContent;
        btn.textContent = "Copiado!";
        setTimeout(() => { btn.textContent = original; }, 1500);
      });
    });
  });
});
