# Deploy hospedado (versão compartilhada, para outras pessoas usarem)

Este documento é só para a versão **hospedada** (várias pessoas, num link). O app local
que já roda no seu PC continua funcionando exatamente igual, sem nada disso -- as duas
versões usam o mesmo código, controlado por variáveis de ambiente.

## Arquitetura

```
Frontend estático (webapp/static/)  →  Vercel
Backend (webapp/main.py + src/)     →  Render (ou Railway/Fly.io) -- sempre ligado
Banco de dados                      →  Turso (compatível com SQLite)
IA (Ollama)                         →  no computador de CADA visitante, nunca no servidor
```

Por quê essa divisão: a Vercel não segura processo nem disco entre chamadas (funções
"dormem"), e este app mantém um modelo de busca semântica carregado na memória o tempo
todo -- por isso o backend precisa de um serviço sempre ligado. O Ollama simplesmente não
roda em nenhum serviço hospedado (precisa de CPU/RAM dedicados e um processo de longa
duração) -- por isso a geração de texto por IA acontece no navegador de cada pessoa,
contra o Ollama que ELA tem instalado, e só o resultado final é compartilhado (cache no
banco) entre todo mundo.

## Passo 1 -- Criar o banco no Turso

```bash
# instalar a CLI do turso (uma vez): https://docs.turso.tech/cli/installation
turso auth login
turso db create radar-credito-incentivado
turso db show radar-credito-incentivado --url        # anota isso -> TURSO_DATABASE_URL
turso db tokens create radar-credito-incentivado      # anota isso -> TURSO_AUTH_TOKEN
```

Depois, rode uma vez localmente para criar as tabelas no banco novo (isso NÃO mexe no seu
`data/radar.db` local -- só mira no Turso porque as variáveis de ambiente estão setadas):

```powershell
$env:TURSO_DATABASE_URL="libsql://SEU-BANCO.turso.io"
$env:TURSO_AUTH_TOKEN="SEU_TOKEN"
cd src
..\.venv\Scripts\python.exe db.py
```

Se aparecer algum erro aqui, é provável que a versão da lib `libsql` instalada tenha uma
API um pouco diferente da testada (`libsql==0.1.11`) -- me avise o erro exato pra eu ajustar.

**Como popular os dados**: rode `refresh.py` e `refresh_editais.py` (mesmos scripts do
app local) uma vez com essas mesmas variáveis de ambiente setadas, para carregar
BNDES/FINEP/editais no banco hospedado. Depois disso, as tarefas agendadas continuam
rodando *localmente* no seu PC contra o banco Turso (ou você configura essas mesmas
tarefas para rodar direto no serviço do Render via cron job -- o Render tem essa opção).

## Passo 2 -- Backend no Render

1. Suba este projeto num repositório GitHub (peça ajuda se não tiver um ainda).
2. Em https://dashboard.render.com: **New > Web Service**, conecte o repositório.
3. Configuração do serviço:
   - **Root Directory**: deixe em branco (raiz do repo)
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn webapp.main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Free (ou o menor pago, se o free tier "dormir" incomodar)
4. Variáveis de ambiente (Environment):
   - `TURSO_DATABASE_URL` = a URL do passo 1
   - `TURSO_AUTH_TOKEN` = o token do passo 1
   - `SITE_USER` = usuário para o login (ex: `artica`)
   - `SITE_PASSWORD` = senha compartilhada com o grupo pequeno de pessoas
   - `ALLOWED_ORIGINS` = o domínio da Vercel do passo 3 (ex: `https://radar-artica.vercel.app`) -- pode
     deixar em branco por enquanto e voltar aqui depois de saber a URL da Vercel
5. Depois do primeiro deploy, gere os embeddings de busca **direto no Render** (Shell, na
   aba do serviço): `cd src && python embeddings.py && python editais_embeddings.py`
   -- esses dois arquivos ficam no disco do próprio serviço (não precisam do Turso).

## Passo 3 -- Frontend na Vercel

1. Edite `webapp/static/js/config.js` e mude `API_BASE_URL` para a URL do Render do passo 2:
   ```js
   window.API_BASE_URL = "https://seu-backend.onrender.com";
   ```
2. Em https://vercel.com: **Add New > Project**, conecte o mesmo repositório.
3. **Root Directory**: `webapp/static` (é um site 100% estático, sem build nenhum).
4. Depois do deploy, volte no Render e atualize `ALLOWED_ORIGINS` com a URL real da Vercel.

## Passo 4 -- Testar

1. Abra a URL da Vercel -- deve pedir usuário/senha (a tela nativa do navegador,
   não uma página customizada) na primeira chamada à API. Use `SITE_USER`/`SITE_PASSWORD`.
2. Confira que os dashboards, filtros e busca funcionam normalmente (sem precisar de IA).
3. Na aba Editais, deve aparecer um selo "Baixar IA local" no topo -- clique nele e siga
   as instruções (baixar Ollama, rodar o comando de modelo, liberar o site no
   `OLLAMA_ORIGINS`). Depois disso o selo deve virar "✓ IA local ativa" e os resumos/o
   endgame passam a gerar pela sua própria máquina.
4. Peça pra outra pessoa (com IA local ativa) gerar o resumo de um edital que você ainda
   não abriu -- depois confira que ele aparece pra você instantaneamente (cache
   compartilhado), sem precisar gerar de novo.

## Manutenção contínua

- **Atualizar o site**: só dar `git push` -- Render e Vercel fazem redeploy automático.
- **Atualizar os dados** (BNDES/FINEP/editais): rodar `refresh.py`/`refresh_editais.py`
  com as variáveis do Turso setadas (dá pra automatizar isso como um "Cron Job" no
  próprio Render, ou continuar rodando do seu PC -- os dados vão pro banco compartilhado
  de qualquer jeito).
- **Trocar a senha de acesso**: mudar `SITE_PASSWORD` nas variáveis de ambiente do Render.
- **Adicionar mais gente ao grupo**: não precisa de conta nem cadastro -- só passar
  usuário/senha pra quem for usar.

## O que NÃO foi testado contra infraestrutura real

Não tenho como criar contas Turso/Render/Vercel nem testar contra um banco Turso de
verdade a partir daqui. O que ESTÁ testado localmente:
- A biblioteca `libsql` (0.1.11) conecta em modo remoto puro e roda `execute`/
  `executemany`/`executescript`/`commit`/`cursor`/`fetchone`/`fetchall` com a mesma
  sintaxe do `sqlite3` (confirmado com um banco `:memory:` local).
- O app local (desktop) continua funcionando 100% igual com `MODO_HOSPEDADO=False`
  (nenhuma variável de ambiente do Turso setada) -- testado após todas as mudanças.

O que precisa de confirmação depois que o Turso estiver configurado de verdade: rodar
`python src/db.py` (cria as tabelas) e depois `python src/refresh.py` uma vez, conferir
que os dados aparecem certinho.
