> Detalhe/histórico extraído do CLAUDE.md em 2026-09-21 (redução de tokens por sessão). Ler só quando a tarefa tocar este assunto especificamente.

## Radar de Crédito Primário — Pipeline CVM

Segundo "modo" da plataforma, construído a partir de 2026-09-16, cobrindo o **mercado de
capitais primário brasileiro** (debêntures, CRI, CRA, notas comerciais/promissórias, letras
financeiras, CDCA, CCB) — complementa o crédito incentivado de fomento (BNDES/FINEP) com o
outro grande canal de captação de dívida das empresas brasileiras. **Esta seção documenta só a
CAMADA DE DADOS** (staging + tabela unificada `operations_primario`) — rotas `/api/primario/*`,
motor de busca e frontend são trabalho de sessões seguintes, construído em cima deste schema.

### Fonte: CVM — Portal de Dados Abertos, dataset "Ofertas Públicas de Distribuição"

Licença ODbL, mantido pela SRE/CVM (órgão regulador oficial), atualizado diariamente.
**ACHADO REAL (2026-09-16)**: a URL do dado esperada terminava em `.csv`
(`.../DADOS/oferta_distribuicao.csv`) — devolve 404 ao vivo. O arquivo de verdade é um `.zip`
no mesmo caminho (`oferta_distribuicao.zip`, ~5.3MB), que **contém DOIS CSVs** dentro (achado
real #2, também só confirmado baixando de verdade): `oferta_distribuicao.csv` (o dataset
pedido) E `oferta_resolucao_160.csv` (dataset relacionado mas diferente — RCVM 160, o rito de
oferta que sucedeu a ICVM 400/476, fora do escopo deste pedido). `src/download_cvm.py` extrai
por NOME do arquivo dentro do zip (nunca por posição/índice — a CVM não documenta nem garante
ordem estável dos membros do zip). Mesmo achado (zip com 2 membros) no `.zip` do dicionário de
dados (`meta_oferta_distribuicao.zip` → `meta_oferta_distribuicao.txt` +
`meta_oferta_resolucao_160.txt`). Encoding **latin-1** (não utf-8), delimitador `;` — confirmado
decodificando e reencodando uma amostra real (`"DEBÊNTURES SIMPLES"` decodifica certo com
`encoding="latin-1"`; o mojibake que aparece em terminais/logs ao longo deste processo é só a
própria console não sabendo renderizar utf-8, não corrupção do dado).

Dataset completo: ~48,9 mil linhas (TODAS as ofertas públicas já registradas/dispensadas desde
1989 — ações, cotas de fundo, BDR, CRI/CRA, debênture etc., republicado por inteiro a cada
atualização, sem filtro nenhum de data). Filtrando só instrumentos de DÍVIDA (ver escopo
abaixo): **12.239 linhas** (confirmado ao vivo, 2026-09-16), cobrindo 1989–2025.

### Instrumentos em escopo (`src/parse_cvm.py::_ESCOPO_REGEX`)

Filtro por regex com `\b` (word boundary) sobre `Tipo_Ativo` normalizado (sem acento,
maiúsculo) — bate tanto o nome por extenso quanto a sigla, mas com boundary nas siglas curtas
(CRI/CRA/CDCA/CCB) para não arriscar falso-positivo por substring cru. Contagem real por
`Tipo_Ativo` no CSV de 2026-09-16 (13 valores distintos observados, todos em escopo):
DEBÊNTURES SIMPLES (4.936), CERTIFICADOS DE RECEBÍVEIS IMOBILIÁRIOS - CRI (3.298), NOTAS
PROMISSÓRIAS (1.753), CERTIFICADOS DE RECEBÍVEIS DO AGRONEGÓCIO - CRA (839), CERTIFICADO DE
RECEBÍVEIS IMOBILIÁRIOS (710, grafia alternativa sem "S" — mesma coisa, mesmo regex bate as
duas), DEBÊNTURES CONVERSÍVEIS (222), CERTIFICADO DE RECEBÍVEIS DO AGRONEGÓCIO (182), NOTAS
COMERCIAIS (168), LETRAS FINANCEIRAS (115), CERTIFICADOS DE DIREITOS CREDITÓRIOS DO
AGRONEGÓCIO - CDCA (11), TOKENS REPRESENTATIVOS DE DEBÊNTURES/SANDBOX REGULATÓRIO (3), CÉDULAS
DE CRÉDITO BANCÁRIO - CCB (1), DEBÊNTURES PERMUTÁVEIS (1).

**Deliberadamente FORA de escopo**: ações, cotas/quotas de fundos (a maioria absoluta das ~49
mil linhas totais — FIDC/FIP/FII/fundo fechado etc., incluindo cotas SÊNIOR/SUBORDINADA de
FIDC, que tecnicamente financiam recebíveis mas são "fundo", não um título de dívida direto),
BDR, warrants (incl. "WARRANTS AGROPECUÁRIOS"), certificado de investimento audiovisual. As 3
linhas com `Tipo_Ativo = "CERTIFICADOS DE RECEBÍVEIS"` (sem qualificador IMOBILIÁRIOS/
AGRONEGÓCIO) ficam de fora de propósito — não dá para saber se é CRI ou CRA sem inventar, e a
regra de ouro deste projeto (ver seção "Linhas Incentivadas") é nunca inferir.

**CORREÇÃO REAL (2026-09-16, sessão de integração do `oferta_resolucao_160.csv` abaixo)**: a
entrada original desta seção dizia que **CPR-F** (Cédula de Produto Rural Financeira) tinha
sido excluído por falta de fonte aberta, e que "CPR não é valor mobiliário registrado na CVM".
**Isso estava ERRADO.** CPR-F *é* um valor mobiliário registrado na CVM — só não aparece neste
arquivo (`oferta_distribuicao.csv`, confirmado: 0 ocorrências de "PRODUTO RURAL"/"CPR" em
`Tipo_Ativo`) porque esse instrumento passa pelo rito automático (Resolução CVM 160), reportado
no SEGUNDO CSV do mesmo zip. Corrigido: 18 linhas reais de CPR-F (Klabin, Suzano, Duratex,
Adami, Eldorado Brasil Celulose, Agropecuária Maggi etc.) agora entram via
`cvm_oferta_resolucao_160_raw` — ver seção "Segunda fonte CVM" abaixo.

### `cvm_oferta_distribuicao_raw` (staging, quase 1:1 com o CSV oficial)

**Escopo de colunas deliberadamente reduzido**: o CSV oficial tem ~30 colunas adicionais de
COMPOSIÇÃO DE INVESTIDORES (`Nr_Pessoa_Fisica`, `Qtd_Fundos_Investimento`,
`Qtd_Investidor_Estrangeiro` etc.) que descrevem QUEM comprou o ativo, não o crédito em si —
fora do escopo de um radar de crédito (poderiam ser adicionadas depois, sem migração nenhuma
nos dados já gravados, se um dia isso virar requisito real — basta estender
`parse_cvm.py::CVM_COLUMNS` e rodar de novo, o CSV de origem continua tendo tudo). Mantidas:
identificação da oferta/processo, emissor/líder/ofertante, datas, classe/série/forma do ativo,
quantidade/preço/valor, flags S/N (incentivo fiscal/regime fiduciário/oferta inicial),
juros/atualização monetária (texto cru, fonte do `indexador_padronizado`).

**`numero_registro_oferta` NÃO é chave natural viável** (achado real, verificado contra o CSV
inteiro antes de desenhar o pipeline) — parecia óbvio (é literalmente "o número de registro da
oferta"), mas **75,8% das linhas de dívida (9.277 de 12.242 candidatas) têm esse campo NULO**:
são ofertas com DISPENSA de registro (`Modalidade_Dispensa_Registro`/`Data_Dispensa_Oferta`
preenchidos nesses casos, nunca um número de registro — a CVM só atribui esse número a ofertas
que de fato passam pelo rito de registro pleno). `Numero_Processo` também não serve sozinho: um
único processo administrativo pode conter **dezenas de séries/emissões diferentes** (confirmado
um processo com 55 séries de debênture, cada uma sua própria linha). Por isso o staging usa a
MESMA estratégia já validada para BNDES/FINEP (ver `incremental.py`): **hash de conteúdo da
linha inteira** (`row_hash`, sobre as colunas de negócio mantidas, não sobre as ~30 excluídas) —
o dataset da CVM também é republicado por inteiro a cada atualização diária, não incremental na
origem. Rodando pela primeira vez (2026-09-16): 12.239 linhas em escopo no CSV, **12.232
inseridas** (7 descartadas por `row_hash` idêntico dentro do mesmo lote — linhas que só
diferiam nas colunas de composição de investidores excluídas do staging, portanto
indistinguíveis nos campos que este projeto de fato guarda).

### `operations_primario` (tabela unificada, mesmo espírito de `operations`)

`src/unify_primario.py::build_operations_primario()` — incremental por `raw_table`+`raw_id`
(nunca por `numero_registro_oferta`, pelos motivos acima), mesmo padrão de
`unify.py::build_operations()`. Diferença de design: `operations` tem 3 estados de
`setor_origem` (nativo/enriquecido/pendente) porque o BNDES tem setor NATIVO na própria
planilha; aqui **todo emissor depende do MESMO caminho de enriquecimento via CNPJ**, então não
existe uma coluna `setor_origem` — o estado "pendente" é só `setor_emissor IS NULL`.

- **`instrumento_padronizado`**: mapa fixo (`INSTRUMENTO_PADRONIZADO_MAP`, chave exata pós-
  normalização, não regex — a essa altura a linha já passou pelo filtro de escopo) para
  `'Debênture'|'CRI'|'CRA'|'Nota Comercial'|'Letra Financeira'|'CDCA'|'CCB'|'Outro'`. Nota
  Promissória e Nota Comercial são **o MESMO instrumento sob nomes diferentes** (a Lei
  14.195/2021 renomeou "nota promissória comercial" para "nota comercial" e trocou o registro
  da B3 pelo da CVM/escritural — mesma natureza econômica) — unificadas sob `'Nota Comercial'`.
- **`setor_emissor`/`subsetor_emissor`/`segmento_emissor`/`porte_emissor`/
  `natureza_juridica_emissor`/`uf_emissor`/`municipio_emissor`/`razao_social_oficial_emissor`**:
  via JOIN contra `cnpj_cnae` (o MESMO cache já usado para enriquecer a FINEP) por
  `cnpj_emissor`. **Extensão feita em `cnpj_cnae` para viabilizar isso**: a tabela nunca teve
  `uf`/`municipio` (BNDES/FINEP já trazem UF/município direto na própria planilha de origem,
  nunca precisaram disso via CNPJ) — adicionadas via `MIGRACOES_COLUNAS` (`ALTER TABLE`,
  nullable, sem backfill retroativo: linhas de `cnpj_cnae` já existentes de BNDES/FINEP ficam
  com `uf`/`municipio` NULL para sempre, o que é aceitável — nada mais consome esses dois campos
  a partir de `cnpj_cnae` hoje). Populadas via `enrich_cnae.py::enrich_pendentes_via_api`
  (BrasilAPI) — a API já devolvia `uf`/`municipio` na mesma chamada usada para CNAE/porte/
  natureza jurídica, só não eram gravados até esta mudança; o job MENSAL em lote
  (`enrich()`, que escaneia `Estabelecimentos*.zip` da RFB) **não foi estendido** para isso
  (`ESTAB_COLS` tem `uf`/`municipio` disponíveis no zip, mas `KEEP_COLS` não os inclui) — só o
  caminho BrasilAPI (usado neste pipeline, volume pequeno o suficiente: ~1,2 mil CNPJs
  distintos) grava esses dois campos por enquanto.
- **`data_referencia`/`ano`/`trimestre`**: `Data_Emissao` (o campo "óbvio") está **ausente em
  82% das linhas em escopo** (achado real — ofertas antigas/dispensadas raramente têm essa data
  digitalizada), então `data_referencia` usa o primeiro campo preenchido nesta ordem de
  preferência (ver `unify_primario.py::_data_referencia`, todos já normalizados para
  `AAAA-MM-DD`): `data_emissao` → `data_registro_oferta` → `data_inicio_oferta` →
  `data_encerramento_oferta` → `data_protocolo` → `data_abertura_processo`. NUNCA inventada — se
  os 6 campos estiverem vazios, fica NULL. `ano`/`trimestre` derivados de `data_referencia`,
  mesmo padrão de `operations.ano`/`operations.trimestre`.
- **`indexador_padronizado`: MELHOR ESFORÇO, propositalmente impreciso — documentado aqui para
  quem for consumir este campo não confiar demais nele.** `Juros`/`Atualização_Monetária` são
  texto livre da CVM desde 1989 (771 e 98 valores distintos só no subconjunto em escopo, ex:
  `"12% A.A."`, `"DI + 2%"`, `"TAXA ANBID"`, `"IGP-M"`, `"VARIAÇÃO CAMBIAL DÓLAR"`, `"NIHIL"`) —
  impossível parsear com precisão total sem inventar. `_indexador_padronizado()` reconhece só os
  4 padrões mais comuns/inequívocos por regex simples: `IPCA+` (contém IPCA/IPCR na atualização
  monetária), `SELIC` (contém SELIC em qualquer um dos dois campos), `CDI` (atualização
  monetária vazia/"NÃO" E juros contém "DI"/"CDI" como palavra inteira — cuidado real evitado
  aqui: `\bC?DI\b` NÃO bate "ANBID" nem "RODI", que não têm a subsequência literal "DI" com
  boundary), `Prefixado` (atualização monetária vazia E juros é uma taxa numérica pura, sem
  DI/CDI/SELIC). Qualquer outro conteúdo real (IGPM, TR, TJLP, ANBID — histórica, uma taxa
  distinta de CDI, NUNCA tratada como equivalente aqui —, variação cambial, IGP-DI, INCC etc.)
  cai em `'Outro'` — nunca em NULL nesse caso, para não parecer "sem indexador" quando na
  verdade só não reconhecemos qual é. NULL fica reservado para quando os dois campos de origem
  estão genuinamente vazios. **Se um dia este campo precisar de mais precisão**: expandir os
  padrões reconhecidos em `_indexador_padronizado()` é seguro (função pura, sem migração), mas
  qualquer expansão deve continuar seguindo a mesma regra de ouro do resto do projeto — nunca
  inventar/inferir um indexador que o texto de origem não afirma claramente.
- **`taxa_valor`/`taxa_tipo` (pedido adicional do usuário, chegou no meio desta mesma sessão,
  logo depois do `indexador_padronizado` acima já estar pronto)**: além de SABER que o
  indexador é CDI, o usuário quer o NÚMERO da taxa/spread (ex: para "CDI + 2,50% a.a." — ver o
  indexador `CDI` E o número `2.5`; para "12,5% a.a." — ver só o número `12.5`). MESMA filosofia
  de melhor esforço do `indexador_padronizado` — `src/unify_primario.py::_extrair_taxa()`, regex
  sobre `juros` (`Atualização_Monetária` carrega o NOME do índice, quase nunca um número de taxa
  junto). `taxa_tipo` tem **3 valores possíveis** (uma extensão deliberada sobre o que foi pedido
  — o usuário sugeriu só `spread`/`taxa_fixa`, mas os dados reais mostraram um terceiro padrão
  genuíno demais pra forçar em uma das duas categorias sem inventar semântica):
  - `'spread'`: aditivo (`+`/`-` explícito, ou a palavra "acrescid[ao] de", ou o número vindo
    ANTES do indexador tipo `"0,75% a.a. + CDI"`) — funciona independente de qual indexador
    precede/segue, então também cobre um spread sobre um indexador que caiu em `'Outro'`
    (IGPM/TR/TJLP/LIBOR/ANBID etc.) — o índice de base continua disponível em
    `indexador_padronizado` + `juros`/`atualizacao_monetaria` crus, nunca escondido atrás do
    número extraído. O `"%"` é **opcional** neste padrão de propósito: `"CDI + 1,75"`/
    `"DI + 2,85 aa"` são spreads reais sem o símbolo — convenção do mercado de crédito privado
    brasileiro é cotar spread sobre DI/CDI/SELIC sempre em pontos percentuais a.a., mesmo quando
    o `%` some do texto (o campo `juros` só existe pra descrever uma taxa de dívida — qualquer
    número aqui depois de um sinal `+`/`-` é uma taxa, nunca outra coisa).
  - `'percentual_indexador'`: **MULTIPLICATIVO, não aditivo** (ex: `"108% do CDI"`,
    `"104% da taxa DI"`) — deliberadamente um `taxa_tipo` DIFERENTE de `'spread'`: tratar
    `"108% do CDI"` como "spread de 108" seria uma leitura errada e enganosa (não são 108 pontos
    percentuais SOMADOS ao CDI, é 108% do próprio CDI — quase o dobro do indexador). Só
    reconhecido quando `indexador_padronizado` já é `'CDI'`/`'SELIC'` (evita ambiguidade com
    outros usos de `%`).
  - `'taxa_fixa'`: prefixado puro (`indexador_padronizado == 'Prefixado'`, número seguido de
    `%`).
  - **BUG REAL corrigido antes de terminar**: as primeiras versões das regex tinham os
    conectivos (`"spread"`, `"sobretaxa"`, `"acrescida"`, `"taxa"`) escritos em minúsculo, mas
    `juros` chega já normalizado em MAIÚSCULO (`remover_acentos(...).upper()`, mesma função
    usada pelo filtro de escopo) — sem `re.IGNORECASE`, nenhuma delas batia contra o texto real
    (`"SPREAD DE 1,5%"` nunca casava com o padrão em minúsculo). Corrigido adicionando
    `re.IGNORECASE` em todas as regex de taxa.
  - **Cobertura real medida** (contra as 12.239 linhas em escopo do CSV de 2026-09-16):
    **515 linhas (~4,2%) com `taxa_valor` extraído** — a grande maioria das linhas tem `juros`
    vazio/`"NAO"`/`"-"` (a mesma razão pela qual `indexador_padronizado` também é `None` em
    10.603 linhas — dado realmente ausente na fonte, não falha de regex). Do subconjunto onde
    `juros` tem conteúdo reconhecível, a cobertura é bem maior; o que ainda fica de fora é
    fraseado raro demais pra valer regex novo agora (ex: `"105% das taxas médias diárias dos
    DI"`, `"101,75 da Taxa DI"` sem `%`) — **documentado aqui, não escondido**: `taxa_valor`
    fica `NULL` nesses casos, nunca um valor chutado.
- **`prazo_dias`/`prazo_meses` (pedido adicional do usuário, mesma sessão)**: diferente de
  indexador/taxa, isso é **dado EXATO, não melhor esforço** — `Data_Vencimento - Data_Emissao`,
  duas datas reais da própria CVM (`src/unify_primario.py::_prazo_dias_e_meses`).
  `prazo_meses` = `prazo_dias / 30,44` (média de dias por mês), arredondado a 1 casa — conversão
  documentada, não inventada, só pra ficar comparável com `operations.prazo_amortizacao_meses`
  (BNDES/FINEP, já em meses). **Só calculável quando AMBAS as datas existem** — confirmado
  contra o CSV real: apenas **1.859 de 12.239 linhas em escopo (15,2%)** têm as duas datas
  preenchidas (`Data_Emissao` sozinha já falta em 82% das linhas, ver `data_referencia` acima).
  **Achado real de qualidade de dado NA PRÓPRIA FONTE**: das 1.903 linhas com as duas datas (nº
  ligeiramente diferente de 1.859 porque conta antes do dedup por `row_hash`), **44 (2,3%) têm
  `Data_Vencimento` ANTERIOR OU IGUAL a `Data_Emissao`** — inconsistência de digitação da CVM,
  não bug deste pipeline (um caso extremo mediu -35.429 dias, quase 97 anos "ao contrário").
  Essas 44 linhas ficam com `prazo_dias`/`prazo_meses` `NULL` de propósito — nunca um prazo
  negativo/zero, que quebraria qualquer comparação/gráfico no frontend depois.
- **Carência: NÃO existe em NENHUMA das duas fontes CVM, confirmado contra os DOIS dicionários
  de dados** (`meta_oferta_distribuicao.txt` E `meta_oferta_resolucao_160.txt`) — nenhum dos
  dois tem um campo equivalente a `prazo_carencia_meses` do BNDES. Diferente do BNDES (que
  declara carência explicitamente na própria planilha), carência de um título de dívida privado
  normalmente só consta na escritura/prospecto do papel, não em nenhum destes registros
  estruturados da CVM. **Deliberadamente não extraído de texto livre** (não há um campo de
  referência que sirva de âncora, ao contrário de indexador/taxa que pelo menos partem de
  `Juros`/`Atualização_Monetária` — tentar inferir carência de descrição livre sem estrutura
  nenhuma seria risco alto de dado errado) — mesma regra de ouro do resto do projeto: sem fonte
  estruturada, sem campo. **Atualização (2026-09-16)**: `oferta_resolucao_160.csv` foi
  integrado (ver seção "Segunda fonte CVM: rito automático/Resolução 160" abaixo) — suas 47
  colunas relevantes foram conferidas uma a uma contra as 71 colunas oficiais do dataset, e
  nenhuma delas descreve carência (o schema é focado em ESTRUTURA/garantia da oferta —
  `Descricao_garantias`/`Agente_fiduciario`/`Titulo_incentivado`/`Tipo_lastro`/`Custodiante` —
  não em condições financeiras do título). Confirmado, não é mais uma suposição: carência
  continua indisponível em ambas as fontes CVM deste pipeline.

Rodando pela primeira vez (2026-09-16) contra produção (Aiven, mesmo `DATABASE_URL` de sempre):
12.232 linhas inseridas em `operations_primario` (1:1 com o staging, nenhuma linha rejeitada),
8.249 emissores ficaram pendentes de enriquecimento (1.472 linhas sem `cnpj_emissor` — nunca vão
resolver, é dado ausente na própria oferta, não erro deste pipeline — + linhas cujo CNPJ ainda
não estava em `cnpj_cnae`), reduzido para **1.242 CNPJs distintos** a resolver via
`enrich_cnae.py::enrich_pendentes_via_api` (BrasilAPI, mesmo mecanismo/rate-limit já usado pela
FINEP — ~0,6s por CNPJ).

### Segunda fonte CVM: rito automático / Resolução 160 (`oferta_resolucao_160.csv`)

**Achado real do coordenador (2026-09-16), DEPOIS que a integração acima já tinha rodado uma
vez**: o MESMO zip oficial (`oferta_distribuicao.zip`) contém um SEGUNDO CSV,
`oferta_resolucao_160.csv` — dataset relacionado mas de **schema DIFERENTE**, focado no rito
automático da Resolução CVM 160 (sucessora da ICVM 400/476 para a maior parte das emissões
modernas). Achado crítico: esse segundo arquivo tem **14.493 linhas cobrindo EXATAMENTE
2023–2026**, contra só **7 linhas** de `cvm_oferta_distribuicao_raw` nesse mesmo período — sem
integrar este arquivo, o radar ficava praticamente cego para a atividade de mercado mais
recente (exatamente o que mais importa para um "radar"). Integrado na mesma sessão que
corrigiu a exclusão indevida do CPR-F (ver acima).

- **`src/download_cvm.py`**: `download_all()` agora baixa o zip principal e o de metadados
  **cada um UMA vez só** e extrai os DOIS membros de cada (antes só extraía
  `oferta_distribuicao.csv`/`meta_oferta_distribuicao.txt` e descartava o resto) — evita baixar
  os mesmos ~5.3MB duas vezes. Novos caminhos: `RESOLUCAO160_CSV_PATH`/`RESOLUCAO160_META_PATH`.
- **`cvm_oferta_resolucao_160_raw`** (staging nova, `src/parse_cvm_resolucao160.py`): MESMO
  padrão de `cvm_oferta_distribuicao_raw` — encoding latin-1, delimitador `;`, incremental por
  `row_hash` (não por chave natural), colunas de composição de investidores excluídas (aqui:
  ~24 colunas `Num_Invest_*`/`Qtde_VM_*`, mesmo critério). **Diferença real encontrada**:
  `Numero_Requerimento` **É confirmado único e não-nulo** nas 14.493 linhas (ao contrário de
  `numero_registro_oferta` no arquivo principal, 76% nulo) — mesmo assim, mantido como coluna
  INFORMATIVA, não como chave de upsert, por consistência com o resto do pipeline (o dataset
  também é republicado por inteiro a cada atualização, não incremental na origem).
- **Escopo de instrumentos**: reaproveita a MESMA regex de `parse_cvm.py`
  (`ESCOPO_REGEX_DIVIDA`, exportada — antes privada `_ESCOPO_REGEX`), estendida com o termo do
  CPR-F (`PRODUTO RURAL FINANCEIRA|\bCPR-F\b`) — inofensivo para o arquivo principal (confirmado
  ao vivo: 0 ocorrências desse termo em `Tipo_Ativo`). Contagem real (CSV de 2026-09-16, campo
  `Valor_Mobiliario` — nomenclatura **diferente** da de `Tipo_Ativo` para o MESMO instrumento,
  ex: "Debêntures" em vez de "DEBÊNTURES SIMPLES", sem sufixo "- CRI"/"- CRA"/"- CDCA", exigiu
  chaves novas em `unify_primario.py::INSTRUMENTO_PADRONIZADO_MAP`): Debêntures 1.938 +
  Debêntures Conversíveis 1, Certificados de Recebíveis Imobiliários 1.868, Notas Comerciais
  770, Certificados de Recebíveis do Agronegócio 587, **Cédula de Produto Rural Financeira
  (CPR-F) 18**, Certificado de Direitos Creditórios do Agronegócio 4, Notas Promissórias 2 —
  **5.188 linhas em escopo** de 14.493 totais (9.305 fora de escopo: majoritariamente Cotas de
  FIDC/FII/FIF/FIP/FIAGRO, Ações, "Outros títulos de securitização" — ambíguo demais, mesmo
  critério de nunca inventar que já exclui "Certificados de Recebíveis" sem qualificador no
  arquivo principal — e as 3 linhas ambíguas "Certificados de Recebíveis").
- **Checagem de DUPLICIDADE entre os dois arquivos (item 5 do pedido, verificado ao vivo)**:
  **ZERO overlap de `Numero_Processo`** entre os dois CSVs (14.493 processos distintos no
  segundo arquivo, nenhum aparece no principal). Uma coincidência de `(CNPJ_Emissor, Emissao)`
  apareceu em 312 combinações, mas inspecionar várias mostrou que são operações DIFERENTES do
  MESMO emissor reaproveitando o número de emissão em programas distintos (ex: um emissor
  serial de securitização com "Emissão 96" de CRI num arquivo e "Emissão 96" de CRA totalmente
  diferente no outro — valores e datas não batem). **Conclusão: os dois arquivos são conjuntos
  DISJUNTOS na prática** — nenhuma lógica de dedup entre eles foi necessária.
- **Campos que este arquivo NÃO tem** (confirmado contra as 71 colunas oficiais):
  `Data_Emissao`/`Data_Vencimento`/`Juros`/`Atualização_Monetária`/`Serie`/`Classe_Ativo`/
  `Especie_Ativo`/`Forma_Ativo`. Por isso, para linhas com `raw_table =
  'cvm_oferta_resolucao_160_raw'`: **`data_emissao`/`data_vencimento`/`prazo_dias`/
  `prazo_meses`/`indexador_padronizado`/`taxa_valor`/`taxa_tipo`/`juros`/
  `atualizacao_monetaria`/`serie`/`classe_ativo`/`especie_ativo`/`forma_ativo` ficam SEMPRE
  `NULL`** (nunca inferidos — em especial, prazo NUNCA foi aproximado a partir das datas de
  PROCESSO deste arquivo, que são conceitos diferentes de vencimento do título). Isso é
  **esperado, documentado, não é bug** — resolve o problema de VOLUME/RECÊNCIA, não o de
  remuneração/prazo do título.
- **`data_referencia` (fallback próprio, `unify_primario.py::_data_referencia_r160`)**: usa os
  campos de data que ESTE arquivo realmente tem, em ordem de preferência: `data_registro` →
  `data_encerramento` → `data_deliberacao_aprovou_oferta` → `data_requerimento` (último recurso,
  mas o ÚNICO campo sem nenhum nulo no dataset inteiro — garante `data_referencia` preenchida
  para praticamente 100% das linhas).
- **6 colunas novas em `operations_primario`** (sempre `NULL` para linhas de
  `cvm_oferta_distribuicao_raw`, que não tem equivalente a nenhuma): `numero_requerimento`
  (traçabilidade — namespace DIFERENTE de `numero_registro_oferta`, nunca confundidos),
  `status_requerimento`, `tipo_lastro` (`'Pulverizado'`/`'Concentrado'`), `agente_fiduciario`,
  `custodiante`, `descricao_garantias`. `titulo_incentivado`/`regime_fiduciario` do arquivo NÃO
  viraram colunas novas — mapeados para as colunas booleanas JÁ existentes `incentivada`/
  `regime_fiduciario` (mesmo significado econômico, Lei 12.431/regime fiduciário).
- **`status_requerimento`: decisão deliberada de NUNCA filtrar silenciosamente.** ~1,1% das
  linhas em escopo (57 de 5.188) têm um status que indica que o requerimento NÃO chegou a virar
  uma oferta efetivamente concluída (`'Oferta Revogada'` 24, `'Requerimento Expirado'` 17,
  `'Registro Caducado'` 15, `'Oferta Suspensa'` 1) — mantidas em `operations_primario` (nunca
  descartadas), mas com o status EXPOSTO nesta coluna nova para quem for construir rotas/
  frontend (fora do escopo desta sessão) poder filtrar se quiser. A maioria é `'Oferta
  Encerrada'` (4.877) ou `'Registro Concedido'`/`'Aguardando Bookbuilding'` (254, em processo
  mas já registrados).
- **Resultado da integração** (rodado ao vivo em produção, 2026-09-16, DEPOIS da primeira
  rodada documentada acima): **5.188 linhas novas** inseridas em `operations_primario` (0
  rejeitadas), total da tabela sobe de 12.232 para **17.420**. Cobertura 2023–2026 sobe de 7
  para **5.193 linhas** (7 do arquivo principal + 5.186 deste novo, 2 linhas do novo arquivo
  ficaram fora da janela por `data_referencia` cair fora dela). Por `instrumento_padronizado`
  na tabela inteira (as duas fontes somadas) depois da integração: Debênture 7.099, CRI 5.873,
  Nota Comercial 2.692, CRA 1.607, Letra Financeira 115, **CPR-F 18**, CDCA 15, CCB 1.
  **Enriquecimento de emissor rodado até o fim nesta sessão** (não deixado para depois): **792
  CNPJs distintos** pendentes resolvidos via `enrich_cnae.py::enrich_pendentes_via_api`
  (BrasilAPI, mesmo mecanismo já usado pela FINEP) — **791/792 resolvidos** (1 não encontrado
  na BrasilAPI, tratado como falha isolada de CNPJ, não interrompe o restante — mesmo
  comportamento já documentado da função), **1.169 linhas reclassificadas** (pendente →
  resolvido; mais que 792 porque um mesmo CNPJ emissor aparece em várias operações). Estado
  final: de 17.420 linhas totais, **1.473 seguem pendentes** — **1.472 delas por não terem
  `cnpj_emissor` na própria oferta** (dado ausente na fonte, nunca vai resolver, não é bug) e
  **1 por CNPJ ainda não resolvido** (o único miss da BrasilAPI nesta rodada).

### Pipeline (`src/refresh_primario.py`)

Orquestrador PRÓPRIO e SEPARADO de `refresh.py` (BNDES/FINEP) — fonte, staging e tabela final
são completamente independentes, só compartilham o cache `cnpj_cnae` (por design, já pensado
para múltiplas fontes). Sequência: `download_cvm.download_all()` (baixa AMBOS os CSVs, ver
seção acima) → `parse_cvm.parse_cvm()` (arquivo principal) →
`parse_cvm_resolucao160.parse_cvm_resolucao160()` (segundo arquivo, rito automático) →
`unify_primario.build_operations_primario()` (processa as DUAS raw tables, cada uma
incrementalmente por `raw_table`+`raw_id` própria, inserindo na MESMA `operations_primario`) →
se sobrar emissor pendente, `enrich_cnae.enrich_pendentes_via_api()` (BrasilAPI, mesma função já
usada pelo refresh semanal da FINEP, só que alvo = CNPJs de `operations_primario`, de QUALQUER
uma das duas fontes) → `unify_primario.reclassificar_emissores_pendentes()`. Log em
`refresh_primario_log` (mesmo formato de `refresh_log`/`refresh_editais_log`;
`cvm_raw_rows` agora soma as linhas novas das DUAS staging tables). **NÃO roda** o job pesado
mensal de `enrich_cnae.py::enrich()`/`enrich_empresas()` (bulk RFB, vários GB) — o volume de
emissores da CVM (milhares, não dezenas de milhares) é resolvido inteiramente pelo caminho leve
via BrasilAPI, sem precisar do job pesado. Automação: `.github/workflows/refresh-primario.yml`,
diário (09:00 UTC, 1h depois do refresh de editais — mesmo secret `DATABASE_URL`), com
`workflow_dispatch` para rodar manualmente.

### Corte de escopo temporal: 2010+ (pedido do usuário, 2026-09-17)

Decisão de produto: o Radar de Crédito Primário passa a focar em emissões a partir de
**2010-01-01** — dado mais antigo removido de propósito, com backup (nunca descartado, mesmo
espírito do Supabase mantido como rede de segurança na migração pro Aiven).

- **Backup antes de apagar**: `operations_primario_pre2010_backup` (mesmas colunas de
  `operations_primario`, criada via `CREATE TABLE ... AS SELECT * FROM operations_primario
  WHERE data_referencia < '2010-01-01'` antes do `DELETE`) — **2.358 linhas** preservadas
  intactas, cobrindo 1989-09-01 a 2009-12-29.
- **`DELETE FROM operations_primario WHERE data_referencia < '2010-01-01'`**: rodado contra
  produção (Aiven) em 2026-09-17, confirmado via `raw_table`+`raw_id` que TODA linha removida
  já estava coberta pelo backup antes do delete (0 linhas órfãs). Linhas com
  `data_referencia IS NULL` **nunca são removidas** por este corte (hoje, 2026-09-17, esse
  caso não ocorre na base real — 0 linhas — mas o filtro preserva o caso de qualquer forma:
  sem data resolvida, não há como confirmar que a linha é de fato anterior a 2010, então
  destruí-la seria apagar dado real sem justificativa).
- **Corte tornado PERMANENTE no pipeline** (`src/unify_primario.py::_filtrar_corte_temporal`,
  `DATA_CORTE_MINIMA = "2010-01-01"`) — aplicado dentro de `_build_primario_ops`/
  `_build_primario_ops_r160`, logo depois de `data_referencia` já calculada e ANTES do
  insert. **Sem isso, o próximo refresh reintroduziria as mesmas 2.358 linhas**: as staging
  tables (`cvm_oferta_distribuicao_raw`/`cvm_oferta_resolucao_160_raw`) continuam com o
  histórico completo (nunca truncadas), e o mecanismo incremental por `raw_id` trata qualquer
  linha ausente de `operations_primario` como "ainda não processada", reinserindo-a na
  próxima rodada — **isso realmente aconteceu uma vez** durante esta mudança (a primeira
  tentativa de `DELETE` foi desfeita por um refresh que rodou antes do filtro permanente
  estar pronto/commitado) e foi corrigido repetindo o `DELETE` só depois do filtro já estar
  em vigor. **Confirmado ao vivo**: rodar `build_operations_primario()` de novo depois do
  filtro entrar em vigor reporta `0 linhas novas` (nenhuma reintrodução).
- Total de `operations_primario` após o corte: **15.076** (era 17.434 — a contagem sobe e
  desce um pouco ao longo do dia com o refresh diário automático, não é um erro de conta).

### Pesquisa de fontes adicionais + melhoria de extração de taxa (2026-09-17)

Pedido do usuário: pesquisar outras fontes ABERTAS/GRATUITAS que cubram o mesmo universo
(debêntures/CRI/CRA/notas comerciais/letras financeiras/CDCA/CCB) e, complementarmente,
melhorar a qualidade de extração das 2 fontes CVM já integradas.

**Pesquisa de fontes novas — conclusão: nenhuma fonte aberta genuinamente melhor foi
encontrada, esforço redirecionado pra qualidade da extração (ver abaixo).** Três candidatos
investigados ao vivo (WebFetch/download real, não só a descrição da página):
- **CVM — "Distribuições de Débentures - Planilha Individualizada"**
  (`dados.cvm.gov.br/dataset/distrpubl`, arquivo `.ods` baixado e inspecionado com
  `pandas`+`odfpy`): é uma série histórica ESTÁTICA/LEGADA, com a própria planilha
  declarando `Data da Atualização do último Período: 02/01/2023` — **não é atualizada desde
  2023-01**, cobre só debêntures sob rito ICVM 400/03 (nem CRI/CRA/CDCA/CCB/notas
  comerciais, nem o rito automático da Resolução 160 que hoje domina o volume recente) e o
  único campo de estrutura é "Garantia" (texto livre, sem carência nem taxa numérica
  separada de "Juros" — mesma limitação que os 2 CSVs já integrados). Conclusão: **pior**
  que o que já temos em cobertura, atualidade E granularidade — descartado.
- **ANBIMA Data** (`data.anbima.com.br`/`developers.anbima.com.br`): API de preços/taxas
  indicativas de MERCADO SECUNDÁRIO (marcação a mercado diária de CRI/CRA/debêntures já
  emitidos) — dado de natureza DIFERENTE do que este radar cobre (ofertas PRIMÁRIAS, o
  evento de emissão em si, não a negociação depois de emitido); também não cobre CDCA/CCB/
  notas comerciais. Mesmo se fosse integrada um dia, seria uma tabela/conceito NOVO
  ("cotação secundária"), não um substituto/complemento direto de `operations_primario` —
  fora do escopo deste pedido (melhorar a mesma extração já existente).
- **B3 — Hub de Dados Públicos** (`b3.com.br/pt_br/dados/hub-de-dados-publicos/`): mesmo
  problema do ANBIMA Data — "fechamento diário por emissor"/"histórico de negócios" é
  MERCADO SECUNDÁRIO (preço de negociação do papel já emitido), não dado de oferta
  primária. Também não cobre CDCA/CCB.
- **Conclusão prática**: a CVM (`oferta_distribuicao.csv` + `oferta_resolucao_160.csv`, já
  integrados) continua sendo a única fonte aberta, gratuita e verificável de OFERTAS
  PRIMÁRIAS deste universo de instrumentos — nenhuma integração nova feita. Esforço
  redirecionado pra extrair MAIS informação útil das 2 fontes já existentes (abaixo).

**Melhoria real de extração: `taxa_valor`/`taxa_tipo` — fallback "spread implícito"
(`src/unify_primario.py::_extrair_taxa`, `_RE_TAXA_BARE`/`_RE_JUROS_AMBIGUO`)**. Investigado
relendo o CSV principal linha a linha (não só o dicionário de dados): das 12.239 linhas em
escopo, **1.012 tinham `juros` preenchido mas `taxa_valor` ficava `NULL`** mesmo antes deste
fix — o padrão mais comum de longe era `juros` ser só um número seco (`"12% A.A."`, `"6%"`,
`"13,5% A.A. - MENSAL"`, 265+54+34+... ocorrências) **enquanto `atualizacao_monetaria` já
tinha um índice real preenchido** (IGPM 330, IPCA 135, TR 71, ANBID 56, IGP-M 50, TJLP 18,
variação cambial/dólar etc. — confirmado amostrando as combinações reais). **Achado-chave**:
a CVM grava índice e taxa em DOIS CAMPOS SEPARADOS desde 1989 — quando o campo de índice
tem conteúdo real e `juros` é só um número seco sem operador `+`/`-` nem menção a índice
nenhum dentro do próprio texto, a convenção do mercado de renda fixa brasileiro (e a própria
separação dos dois campos oficiais) é ADITIVA (índice + juros), exatamente a mesma lógica
que `'taxa_fixa'` já usava pra número seco quando o índice está VAZIO — só que aqui o índice
existe. Implementado como um NOVO fallback (`taxa_tipo='spread'`), rodando só depois de todos
os padrões anteriores falharem, e só quando `indexador_padronizado != "Prefixado"` (senão
duplicaria a lógica de `'taxa_fixa'`, que já cobre exatamente esse caso quando não há
índice). **Exclusão deliberada de ambiguidade**: `juros` contendo `" OU "` (ex: `"12% A.A.
OU LIBOR + 3,5%"`, `"11,2% ou 9,4% aa, antes ou após 01/12/2003"` — duas taxas alternativas
no mesmo campo) fica de fora de propósito — escolher uma das duas seria inventar qual se
aplica. **BUG REAL corrigido pelo coordenador antes do merge (2026-09-17)**: a guarda de
`"OU"` implementada nesta sessão só protegia o fallback NOVO acima — os 3 padrões de
`'spread'` já EXISTENTES antes desta sessão (`_RE_SPREAD_SINAL_ANTES`/`_RE_SPREAD_ACRESCIDA`/
`_RE_SPREAD_SINAL_DEPOIS`) rodavam ANTES da guarda e extraíam o número de qualquer jeito
quando havia um sinal `+`/`-` explícito, mesmo com `"OU"` no meio do texto (reproduzido ao
vivo: `_extrair_taxa("12% A.A. OU LIBOR + 3,5%", "Outro")` devolvia `(3.5, 'spread')` em vez
de `(None, None)`). Corrigido movendo a guarda pra antes de TODOS os padrões (não só o
último). **Confirmado que isso não afetou nenhuma linha real**: 0 linhas em produção têm
`taxa_valor` extraído E `"OU"` no texto de `juros` (checado direto contra o banco) — o gap
era real mas latente, sem impacto nos dados já gravados; ficava como risco pro próximo
refresh diário trazer um caso assim. **Nunca inventa nada**: o número sempre vem literalmente
do texto de `juros`, nunca calculado/estimado — mesma regra de ouro de sempre.

**Cobertura medida (antes → depois, mesmas 12.239 linhas em escopo do CSV de 2026-09-17)**:
**515 (~4,2%) → 1.373 (~11,2%)** — quase o triplo, `taxa_tipo` novo contribuindo 1.146
`'spread'` (a maioria do ganho), 144 `'percentual_indexador'` e 83 `'taxa_fixa'` já
existentes antes (números totais depois do fix, não só o delta). **Backfill rodado contra
produção** (`unify_primario.backfill_taxa_e_prazo()`, já existia — reaproveitado, nenhuma
função nova precisou ser escrita pra isso): sobre as 15.076 linhas já em `operations_primario`
(pós-corte 2010+), `taxa_valor` preenchido subiu de **87 para 239** (86 `'spread'` implícito
+ 14 `'percentual_indexador'` + 9 `'taxa_fixa'` já existentes, dos 239 totais — o ganho
relativo é menor que no CSV completo porque o padrão "número seco + índice legado tipo
IGPM/TR/BTN" era mais comum em ofertas ANTIGAS, que o corte 2010+ já removeu; instrumentos
modernos tendem a escrever a taxa já com operador `+`/`-` explícito, capturado pelos padrões
`'spread'` anteriores). `prazo_dias` não mudou (534 preenchidos, mesmo valor de antes) — o
backfill recalcula os dois juntos mas a lógica de prazo não foi alterada nesta sessão (ver
abaixo).

**`prazo_dias`/`prazo_meses`: nenhuma melhoria segura encontrada.** Investigado se havia
mais campos de data utilizáveis nos 2 dicionários de dados oficiais (`meta_oferta_
distribuicao.txt`/`meta_oferta_resolucao_160.txt`, os 2 relidos por completo nesta sessão,
71+41 campos conferidos um a um) — confirmado que `Data_Emissao`/`Data_Vencimento`
continuam sendo os ÚNICOS dois campos de data que descrevem o TÍTULO em si (todas as outras
datas — `Data_Registro_Oferta`/`Data_Protocolo`/`Data_Requerimento` etc. — descrevem o
PROCESSO administrativo, não o vencimento do papel; usar essas pra aproximar prazo seria
inventar). A baixa cobertura (15,2% no CSV completo, ver seção acima) é uma limitação REAL
da fonte (ofertas antigas/dispensadas raramente têm essas 2 datas digitalizadas), não um gap
de código a corrigir — nenhuma mudança feita aqui, documentado pra não reabrir essa
investigação à toa numa sessão futura.

**Nenhuma mudança em `.github/workflows/refresh-primario.yml`**: o fix de `_extrair_taxa` é
puramente computacional (nova regra de regex sobre colunas já lidas), sem migração de
schema nem novo download/fonte — o próximo refresh diário automático já aplica a regra nova
em qualquer linha nova via `_build_primario_ops` normalmente, sem precisar de nenhum passo
extra no workflow. O backfill acima (`backfill_taxa_e_prazo()`) foi rodado manualmente UMA
VEZ contra produção para corrigir o histórico já gravado — mesmo padrão de
`backfill_busca_primario()` (ver seção "API e Busca" abaixo), não é algo que o workflow
precisa repetir automaticamente.

### Escopo desta sessão (fundação — outras sessões constroem em cima)

Esta sessão entregou SÓ a camada de dados (staging + `operations_primario` + schema +
enriquecimento de emissor), deliberadamente sem tocar em: rotas `/api/primario/*` (FastAPI),
motor de busca, frontend/abas novas. O schema de `operations_primario` já está estável o
suficiente para outra sessão começar a codificar contra ele em paralelo, mesmo antes do
enriquecimento de 100% dos emissores pendentes terminar (o campo `setor_emissor`/`uf_emissor`
IS NULL é um estado normal e esperado, não um bug a esperar sumir). **Motor de busca + rotas
construídos na sessão seguinte, mesmo dia — ver seção própria abaixo, "Radar de Crédito
Primário — API e Busca".** **A integração do segundo arquivo CVM
(`oferta_resolucao_160.csv`, ver seção própria acima) foi feita por OUTRA sessão seguinte,
também no mesmo dia** — mesmo espírito: só camada de dados, nenhuma rota/busca/frontend
tocada, schema aditivo (6 colunas novas, todas nullable, nenhuma coluna existente removida ou
renomeada) para não quebrar quem já estivesse codificando contra o schema anterior em paralelo.
