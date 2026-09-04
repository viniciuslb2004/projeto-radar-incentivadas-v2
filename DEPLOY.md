# Deploy hospedado (versão compartilhada, para outras pessoas usarem)

Este documento é só para a versão **hospedada** (várias pessoas, num link). O app local
que já roda no seu PC continua funcionando exatamente igual, sem nada disso -- as duas
versões usam o mesmo código, controlado por variáveis de ambiente (a principal sendo
`DATABASE_URL`).

## Arquitetura

```
Frontend estático (webapp/static/)   →  Vercel (CDN, arquivos servidos direto)
Backend (webapp/main.py + src/)      →  Vercel Functions (runtime Python, api/index.py)
Banco de dados                       →  Postgres (Supabase)
Embedding da busca (transformers.js) →  no navegador de CADA visitante, nunca no servidor
```

Não há mais IA generativa (Ollama) neste app -- resumos, refino de busca e narrativa
foram removidos (a plataforma agora só serve dados já processados por uma etapa externa,
mais busca semântica via embeddings, que continua 100% intacta).

Frontend e backend agora vivem no **mesmo projeto/domínio da Vercel** (ver `vercel.json`
na raiz do repo): `api/index.py` é o ponto de entrada que a Vercel reconhece como função
Python (importa o objeto `app` de `webapp/main.py` sem duplicar nenhuma lógica), e as
rotas `/api/*` são roteadas para essa função enquanto tudo o mais é servido como arquivo
estático a partir de `webapp/static/`. Isso substitui a divisão antiga (frontend na
Vercel + backend num serviço à parte, sempre ligado, tipo Render/Railway/Fly.io) -- não
há mais backend separado para manter no ar, nem CORS entre domínios diferentes (por isso
`webapp/static/js/config.js` agora usa sempre uma URL relativa, `API_BASE_URL = ""`).

**Isso não elimina a preocupação de memória/tamanho que motivou o embedding client-side**
-- só troca de fornecedor. Funções serverless da Vercel também têm teto de tamanho de
bundle (e de memória/tempo de execução), então carregar `sentence-transformers`/`torch`
dentro da função ainda seria um problema, exatamente como era no free tier do Render. Por
isso o design se mantém: o cálculo do embedding da busca do usuário roda no navegador
(`webapp/static/js/embeddings-client.js`, via `transformers.js`/ONNX, WASM -- sem custo de
memória no servidor), e o backend, no modo hospedado, nunca importa/carrega
`sentence_transformers`/`torch` em tempo de execução -- só faz a matemática (produto
escalar via numpy) contra os vetores do corpus já pré-calculados
(`data/embeddings.npz`/`data/editais_embeddings.npz`, versionados no próprio repo). Por
esse motivo a função da Vercel usa `api/requirements.txt` (dependências enxutas: fastapi,
psycopg, requests, numpy, pandas, python-dotenv) em vez do `requirements.txt` da raiz, que
serve o pipeline de dados local + os workflows do GitHub Actions e inclui
torch/sentence-transformers/pandas/openpyxl/pypdf/sqlalchemy -- pacotes bem mais pesados
que a API hospedada nunca usa em tempo de execução.

> **Confirmado contra deploy real (2026-09-03):** a 1ª tentativa usou um
> `requirements-api.txt` na raiz do repo -- a Vercel ignorou esse nome e instalou o
> `requirements.txt` pesado da raiz mesmo assim ("Total bundle size (1143.54 MB) exceeds
> the maximum function size (500 MB)"). Corrigido movendo o arquivo pra
> `api/requirements.txt` (ao lado da própria função, colocação que a Vercel realmente
> respeita) -- build seguinte confirmado dentro do limite.

## Passo 1 -- Criar o banco no Supabase

1. Crie um projeto em https://supabase.com (grátis para o volume de dados deste app).
2. Nas configurações do projeto (Database → Connection string), copie a connection
   string do Postgres -- essa é a variável `DATABASE_URL`.
3. Rode uma vez localmente para criar as tabelas no banco novo (isso NÃO mexe em nenhum
   banco local antigo -- o projeto não usa mais SQLite local nenhum, só fala com este
   Postgres, local ou em produção):

```powershell
# num arquivo .env na raiz do repo (carregado automaticamente via python-dotenv):
# DATABASE_URL=postgresql://...sua connection string do Supabase...
cd src
..\.venv\Scripts\python.exe db.py
```

**Como popular os dados**: rode `refresh.py` e `refresh_editais.py` (mesmos scripts do
app local) uma vez com `DATABASE_URL` apontando para o Supabase, para carregar
BNDES/FINEP/editais no banco hospedado. As tarefas agendadas continuam rodando
*localmente* no seu PC (ou via GitHub Actions, se configurado) contra esse mesmo banco
Supabase -- o app hospedado só lê o banco, nunca escreve nele sozinho.

## Passo 2 -- Deploy na Vercel (frontend + backend juntos)

1. Suba este projeto num repositório GitHub (peça ajuda se não tiver um ainda).
2. Em https://vercel.com: **Add New > Project**, conecte o repositório.
3. **Root Directory do projeto**: deixe em branco/raiz do repo (NÃO `webapp/static` como
   na configuração antiga) -- a Vercel precisa enxergar `vercel.json`, `api/` e
   `webapp/static/` ao mesmo tempo, e todos os três só ficam visíveis juntos se a raiz do
   projeto for a raiz do repositório. `vercel.json` já define `outputDirectory` apontando
   para `webapp/static`, então o site estático continua saindo do lugar certo mesmo com a
   raiz do projeto na raiz do repo.
4. Variáveis de ambiente (Environment Variables, nas configurações do projeto):
   - `DATABASE_URL` = a connection string do Supabase (passo 1)
   - `SITE_USER` = usuário para o login (ex: `artica`)
   - `SITE_PASSWORD` = senha compartilhada com o grupo pequeno de pessoas
   - `ALLOWED_ORIGINS` pode ficar em branco/sem configurar -- CORS só importava quando
     frontend e backend viviam em domínios diferentes (arquitetura antiga); agora os dois
     estão sempre no mesmo domínio da Vercel.
5. Confirme também que a opção que expõe as variáveis de ambiente de sistema da própria
   Vercel (`VERCEL`, `VERCEL_ENV`, etc.) está habilitada nas configurações do projeto --
   `webapp/main.py` usa a variável `VERCEL` para decidir se deve (ou não) montar o
   servidor de arquivos estáticos embutido (só deve rodar localmente; ver comentário no
   código). Sem essa variável chegando ao processo, o pior efeito é esse mount rodar à
   toa dentro da função (peso extra no bundle), não um erro -- mas vale confirmar.
6. Depois de cada deploy, vale conferir no log de build se o bundle da função ficou
   dentro do limite de 500MB (ver nota na seção Arquitetura sobre `api/requirements.txt`).

## Passo 3 -- Testar

1. Abra a URL da Vercel -- deve pedir usuário/senha (a tela nativa do navegador,
   não uma página customizada) na primeira chamada à API. Use `SITE_USER`/`SITE_PASSWORD`.
2. Confira que os dashboards, filtros e busca funcionam normalmente.
3. Na aba Editais, teste a busca livre (endgame) e confirme que a lista de editais
   aparece rankeada por similaridade -- é 100% embeddings (client-side), sem nenhuma
   etapa de IA generativa envolvida.
4. Na aba Minha Empresa, digite um CNPJ e confirme que a lista de editais elegíveis
   troca de "todos os editais abertos aplicáveis a empresas" para "ordenados por IA
   pelo que mais tem a ver com o que sua empresa faz" alguns segundos depois de
   carregar (upgrade progressivo via embedding calculado no navegador, ver
   `webapp/static/js/elegibilidade.js`).

## Manutenção contínua

- **Atualizar o site**: só dar `git push` -- a Vercel faz redeploy automático (frontend e
  backend juntos, no mesmo deploy).
- **Atualizar os dados** (BNDES/FINEP/editais): rodar `refresh.py`/`refresh_editais.py`
  com `DATABASE_URL` apontando para o Supabase (dá pra automatizar isso via GitHub
  Actions ou continuar rodando do seu PC -- os dados vão pro banco compartilhado de
  qualquer jeito).
- **IMPORTANTE -- atualizar os vetores de busca**: `refresh.py`/`refresh_editais.py`
  também regeram `data/embeddings.npz`/`data/editais_embeddings.npz` localmente. Como a
  função da Vercel só enxerga o que está no próprio repositório Git (sem disco
  persistente entre deploys, mesma lógica que já valia no Render), depois de cada refresh
  é preciso `git add data/embeddings.npz data/editais_embeddings.npz`, commit e
  `git push` -- sem isso, o próximo redeploy vai continuar servindo os vetores antigos
  (operações/editais novos não aparecem na busca, embora apareçam nos dashboards, que não
  dependem desses vetores).
- **Trocar a senha de acesso**: mudar `SITE_PASSWORD` nas variáveis de ambiente do
  projeto na Vercel.
- **Adicionar mais gente ao grupo**: não precisa de conta nem cadastro -- só passar
  usuário/senha pra quem for usar.

## O que NÃO foi testado contra infraestrutura real

Esta seção documenta a migração de Render+Turso para Vercel (função Python)+Supabase.
Não há como criar um projeto Vercel de verdade nem rodar um deploy real a partir daqui.
O que ESTÁ testado localmente: o app roda corretamente com `uvicorn webapp.main:app`
contra o Postgres do Supabase (`DATABASE_URL` num `.env` local), incluindo as rotas de
busca/editais/elegibilidade, e `api/index.py` importa `webapp.main:app` sem erro de
import (`python -c "import sys; sys.path.insert(0, 'api'); import index"` a partir da
raiz do repo).

O que precisa de confirmação depois que o projeto Vercel estiver configurado de verdade:

- A sintaxe exata de configuração do runtime Python em `vercel.json` -- a Vercel mudou
  essa convenção mais de uma vez ao longo do tempo (o antigo builder `@vercel/python`
  com `builds`/`routes` foi substituído por detecção automática + `rewrites`/`functions`,
  conforme a documentação consultada nesta migração). Como a Vercel pode mudar isso de
  novo, vale conferir a documentação oficial (https://vercel.com/docs/functions/runtimes/python)
  antes do primeiro deploy real.
- Se a variável `VERCEL` chega mesmo ao processo da função (depende da opção "Enable
  access to System Environment Variables" estar marcada nas configurações do projeto --
  ver Passo 2, item 5). Sem isso, o único efeito colateral é o mount de arquivos
  estáticos rodar à toa dentro da função (sem quebrar nada).
- Se o `outputDirectory: "webapp/static"` em `vercel.json` sozinho é suficiente para a
  Vercel servir esses arquivos como site estático sem nenhum "Build Command" configurado
  (o site é 100% estático, sem build nenhum) -- se não for, o ajuste manual seria
  configurar um Build Command vazio/no-op nas configurações do projeto.
- Uma conexão real fim-a-fim contra o Supabase a partir de uma função rodando de fato na
  Vercel (região/latência, limite de conexões simultâneas do plano gratuito do Supabase
  sob a carga de múltiplas invocações concorrentes da função).

**Embedding client-side (transformers.js)**: testado no navegador (Chrome) contra o
backend rodando localmente -- o modelo `Xenova/paraphrase-multilingual-MiniLM-L12-v2`
carrega via CDN (jsDelivr) e devolve vetores comparáveis aos do servidor para as queries
de teste usadas. O que NÃO foi testado: o comportamento em navegadores além do testado
(Safari/Firefox devem funcionar via WASM, mas não foram verificados aqui). Se a busca no
site hospedado devolver resultados estranhos (score baixo em tudo, ranking sem sentido)
depois que isso for ao ar, o primeiro lugar para olhar é se o pooling/normalização do
modelo client-side realmente bate com o `model.encode(..., normalize_embeddings=True)` do
servidor (ver comentário no topo de `webapp/static/js/embeddings-client.js`).
