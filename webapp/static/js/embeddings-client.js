// Calcula o embedding da query de busca DIRETO NO NAVEGADOR (transformers.js, roda um
// modelo ONNX via WASM) -- so usado no modo HOSPEDADO (Render free tier tem 512MB de
// RAM; carregar o sentence-transformers no servidor estoura esse limite e derruba o
// processo, ver DEPLOY.md). O servidor, nesse modo, so faz o produto escalar (numpy)
// contra os vetores precalculados do corpus (data/embeddings.npz / data/
// editais_embeddings.npz) -- nunca importa/carrega sentence_transformers.
//
// IMPORTANTE (nao muda nada no app local/desktop): este arquivo so faz o import()
// dinamico do transformers.js e baixa o modelo quando embutirQuery() e efetivamente
// CHAMADO -- so acontece quando window.MODO_HOSPEDADO === true (ver busca.js/
// editais.js). No app local, esta funcao nunca e chamada, entao nada aqui roda: zero
// download, zero custo, comportamento identico a antes desta mudanca.
//
// Correspondencia com o servidor (CRITICO -- se isso estiver errado, a busca funciona
// mas devolve resultados sem sentido nenhum, sem erro nenhum aparecer):
// - Modelo: server usa sentence-transformers "paraphrase-multilingual-MiniLM-L12-v2"
//   (ver MODEL_NAME em src/embeddings.py) com model.encode(textos,
//   normalize_embeddings=True) -- que por baixo dos panos faz MEAN POOLING sobre os
//   tokens (usando a attention mask) + normalizacao L2.
// - Aqui usamos "Xenova/paraphrase-multilingual-MiniLM-L12-v2" -- a conversao ONNX
//   oficial (Hugging Face Hub, mantida pelo mesmo time do transformers.js) do MESMO
//   checkpoint sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 usado pelo
//   servidor -- com { pooling: "mean", normalize: true } no pipeline, reproduzindo
//   exatamente os mesmos dois passos. Os vetores resultantes (384 dims) sao
//   diretamente comparaveis por produto escalar (== cosseno, ja que ambos os lados
//   sao normalizados) com os vetores precalculados do servidor.
// - dtype "q8" (int8 quantizado) mantem o download na casa de dezenas de MB em vez de
//   ~470MB (fp32, dominado pela tabela de embeddings do vocabulario multilingue XLM-R)
//   -- pequena perda de precisao numerica, aceitavel para ranking de busca semantica.
//   O navegador cacheia o modelo (Cache API do proprio transformers.js) depois do
//   primeiro uso -- buscas seguintes na mesma maquina nao baixam de novo.

const TRANSFORMERS_JS_CDN = "https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.2.0";
const EMBEDDING_MODEL_ID = "Xenova/paraphrase-multilingual-MiniLM-L12-v2";
const EMBEDDING_DTYPE = "q8";

let _transformersModPromise = null;
let _extractorPromise = null;

function _carregarTransformersJS() {
  if (!_transformersModPromise) {
    _transformersModPromise = import(TRANSFORMERS_JS_CDN);
  }
  return _transformersModPromise;
}

// `onProgress` (opcional) recebe os eventos de progresso do proprio transformers.js
// (ex: {status:"progress", file, progress, loaded, total}) -- usado pelo chamador so
// para mostrar "baixando modelo (X%)..." na primeira vez.
async function _getExtractor(onProgress) {
  if (!_extractorPromise) {
    _extractorPromise = (async () => {
      const { pipeline, env } = await _carregarTransformersJS();
      // App 100% estatico (sem pasta de modelos local) -- so busca no Hub mesmo.
      env.allowLocalModels = false;
      return pipeline("feature-extraction", EMBEDDING_MODEL_ID, {
        dtype: EMBEDDING_DTYPE,
        progress_callback: onProgress,
      });
    })();
  }
  return _extractorPromise;
}

// Calcula o embedding de `texto` -- devolve um array simples de numeros (384 dims),
// ja mean-pooled + L2-normalizado, pronto para mandar pro servidor (POST /api/busca,
// /api/editais/buscar etc, ver busca.js/editais.js). `onProgress` e opcional (so
// dispara de verdade na primeira chamada, enquanto o modelo ainda esta baixando).
async function embutirQuery(texto, onProgress) {
  const extractor = await _getExtractor(onProgress);
  const saida = await extractor(texto, { pooling: "mean", normalize: true });
  return Array.from(saida.data);
}

window.embutirQuery = embutirQuery;
