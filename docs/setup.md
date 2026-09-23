# Executar e testar o Portfolio Tracker

## Neste computador: um terminal no VS Code

Abra a pasta do projeto e **Terminal → Novo Terminal**. Na raiz, execute:

```powershell
.\scripts\start-local.ps1 -SkipBuild
```

Abra **http://127.0.0.1:8000**. Esse comando inicia o PostgreSQL portátil preparado
em `.local`, verifica o banco, aplica migrações pendentes, carrega idempotentemente
`data/instruments.csv` e serve a API e a interface React compilada no mesmo endereço.
Não limpa nem reinicializa o banco.

Se a política do PowerShell impedir a execução do script, use somente para essa execução:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -SkipBuild
```

Use `Ctrl+C` para parar a aplicação. O PostgreSQL continua ativo. Para encerrá-lo:

```powershell
.\.local\pgsql\bin\pg_ctl.exe -D .local/pgdata -m fast -w stop
```

Para recompilar a interface após mudanças, execute o script sem `-SkipBuild`.
Não inicie duas instâncias da API na mesma porta.

## Reinicializar o banco local de desenvolvimento

Para começar um teste manual sem dados antigos, encerre a API e execute:

```powershell
.\scripts\reset-local-db.ps1 -ConfirmReset
```

Esse comando é destrutivo: encerra conexões, remove e recria o banco, aplica todas
as migrações e carrega o catálogo. Há três proteções: a confirmação explícita é
obrigatória, o host de `DATABASE_URL` deve ser `localhost`/`127.0.0.1`, e o nome do
banco deve ser exatamente `portfolio_tracker` ou terminar em `_dev`. O script recusa
qualquer outro alvo. Ele não pertence a migrações de produção e não é executado no
startup normal.

O reset rejeita opções de query na URL e exige o driver `postgresql+psycopg`,
evitando que a migração use um destino diferente do banco local validado.

Para somente reaplicar o catálogo controlado, sem apagar dados:

```powershell
.\.venv\Scripts\python.exe -m src.instrument_catalog
```

A carga é idempotente e falha se um símbolo de provedor já pertencer a outro
instrumento canônico.

## Desenvolvimento com atualização automática

Com PostgreSQL ativo, abra dois terminais na raiz:

```powershell
# Terminal 1: API
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m src.instrument_catalog
.\.venv\Scripts\python.exe -m uvicorn src.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
# Terminal 2: React
cd frontend
npm run dev
```

Abra **http://127.0.0.1:5173**. O Vite encaminha `/api` para a API na porta 8000.
Se estiver usando esse modo, encerre antes o processo iniciado por `start-local.ps1`.

## Primeiro teste manual

1. Selecione a carteira migrada ou crie uma carteira separada para testes.
2. Clique em **Nova transação** e registre uma compra fictícia de 10 unidades a 20.
3. Abra **Cotações**, selecione o ativo e registre fechamento de 30 na data atual.
4. Confira quantidade 10, preço médio 20 e valor atual 300 em **Posições**.
5. Abra **Desempenho** para ver o ganho legado de 100.
6. Edite a quantidade para 5, confira o recálculo e recarregue a página para confirmar persistência.

Não use os valores fictícios acima na carteira real. Os resultados não têm conversão
de moedas. O histórico antigo de cotações termina na data do cache original;
use atualização Yahoo ou cotações manuais para datas mais recentes.

## Instalação em outra máquina

Requisitos: Python 3.13 ou 3.14, Node 22 e PostgreSQL 17. As dependências da entrega
foram verificadas em Python 3.14 e Node 22. O PostgreSQL portátil em `.local` é
específico desta máquina e não é versionado.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Edite `DATABASE_URL` em `.env` com as credenciais do seu banco. Nunca publique esse arquivo.
Com PostgreSQL ativo:

```powershell
.\.venv\Scripts\python.exe -m src.bootstrap
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m src.instrument_catalog
cd frontend
npm ci
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

`bootstrap` cria o banco apenas se não existir, usando um usuário com essa permissão.
Se o administrador já criou o banco, pode ir diretamente para `alembic upgrade head`.

### Alternativa Docker

Com Docker Desktop ativo, execute na raiz:

```powershell
docker compose up --build
```

Abra **http://127.0.0.1:8000**. O Compose cria banco e aplicação em contêineres.
Pare o PostgreSQL portátil antes, pois ambos usam a porta 5432. O banco do Docker é
separado do banco portátil: os dados não são copiados automaticamente. Para parar,
use `docker compose down`; não adicione `-v`, que removeria o volume de dados.
As credenciais de exemplo do Compose destinam-se apenas ao ambiente local.

## Importar dados do código antigo

Leitura de validação, sem gravar no banco:

```powershell
.\.venv\Scripts\python.exe -m src.import_legacy src/db/transactions.pkl --assets src/db/assets.pkl --dry-run
```

Importação definitiva:

```powershell
.\.venv\Scripts\python.exe -m src.import_legacy src/db/transactions.pkl --assets src/db/assets.pkl
```

Cria uma carteira migrada com transações e cotações originais. Repetir o mesmo
arquivo não duplica transações. Para escolher uma carteira vazia, use
`--portfolio-id ID`. As posições são recalculadas; `positions.pkl` não é necessário.
O leitor restringe os tipos Python aceitos; use apenas arquivos locais conhecidos
do projeto. Não existe endpoint de upload de pickle.

## Importar transações CSV/XLSX

Na aba **Transações**, clique em **Importar transações**, ao lado de
**+ Nova transação**. A página dedicada fica em
**http://127.0.0.1:8000/#/transactions/import** (ou porta 5173 no Vite).
Use **Voltar para Transações** para retornar ao histórico. A navegação usa hashes
no mesmo shell React, sem dependência de roteamento ou configuração adicional no servidor.

1. Confira a carteira selecionada no topo. Para testes, crie uma carteira separada.
2. Clique em **Baixar planilha modelo** e substitua/remova as três operações fictícias.
3. Em **Selecionar arquivo**, envie CSV ou XLSX e revise os valores da prévia.
4. Corrija os erros indicados por linha/coluna e selecione o arquivo novamente.
5. Clique em **Confirmar importação** quando todas as linhas forem válidas.

Nenhuma transação é salva durante a prévia. Confirmar recalcula as posições pelo
mesmo fluxo existente. A proteção de duplicatas usa o conteúdo exato do arquivo
por carteira; um arquivo alterado ou reexportado não é necessariamente reconhecido.

### Estrutura e colunas aceitas

CSV usa UTF-8, com ou sem BOM, e separador vírgula, ponto e vírgula ou tabulação.
XLSX lê a aba ativa. A primeira linha é o cabeçalho; a ordem das colunas é livre.
Maiúsculas/minúsculas e espaços nas extremidades dos cabeçalhos são ignorados.
Cabeçalhos duplicados, aliases repetidos do mesmo campo e células excedentes sem
cabeçalho são rejeitados. Colunas desconhecidas são ignoradas.

| Coluna | Obrigatória / opcional | Tipo | Formato / valores | Exemplo | Descrição / observações |
| --- | --- | --- | --- | --- | --- |
| `ticker` | Obrigatória | Texto | 1–40 caracteres: A–Z, a–z, 0–9 e `. ^ = : / _ -` | `FICTICIO-BR` | Convertido para maiúsculas. Alias: `asset`. |
| `broker` | Obrigatória | Texto | 1–120 caracteres | `Corretora Fictícia` | Corretora. |
| `type` | Obrigatória | Enum textual | `Buy`, `Sell`, `Compra`, `Venda`, sem distinção de maiúsculas/minúsculas | `Buy` | Compra ou venda; espaços externos removidos. Alias: `transaction_type`. |
| `trade_date` | Obrigatória | Data | `AAAA-MM-DD` ou célula de data no XLSX | `2024-01-02` | Não pode ser futura. Alias: `trade date`. |
| `settlement_date` | Obrigatória | Data | `AAAA-MM-DD` ou célula de data no XLSX | `2024-01-04` | Igual ou posterior à negociação. Alias: `settlement date`. |
| `quantity` | Obrigatória | Decimal | Maior que zero | `10.5` | Quantidade. |
| `unit_price` | Obrigatória | Decimal | Zero ou positivo | `25.50` | Preço unitário. Aliases: `price`, `unit price`. |
| `transaction_currency` | Condicional | Texto | Exatamente 3 letras A–Z/a–z | `BRL` | Obrigatória para cripto e ativos personalizados. Ações e ETFs resolvidos pelo catálogo usam a moeda nativa quando omitida; um valor diferente é rejeitado. Alias: `currency`. |
| `fx_rate` | Opcional | Decimal | Maior que zero quando informado | `5.25` | Vazio: 1 para BRL; busca histórica para moeda estrangeira. Alias: `fx rate`. |
| `allocation_class` | Opcional | Texto | 1–120 caracteres quando informado | `Exemplo` | Vazio/ausente: `Sem classe`. Alias: `allocation class`. |
| `brokerage_fee` | Opcional | Decimal | Zero ou positivo | `1.25` | Vazio/ausente: 0. Alias: `brokerage fee`. |
| `other_fees` | Opcional | Decimal | Zero ou positivo | `0.50` | Vazio/ausente: 0. Alias: `other fees`. |
| `notes` | Opcional | Texto | Até 5.000 caracteres | `Exemplo fictício` | Vazio/ausente: texto vazio. |

Em texto, use ponto decimal e nenhum símbolo monetário/separador de milhar:
`1234.56`, não `1.234,56`. Células numéricas do Excel são aceitas mesmo quando
exibidas com vírgula. Para muitos dígitos, use células de texto para evitar a
perda de precisão do próprio Excel. O parser também aceita notação científica
(`1e2`) e sublinhados (`1_000.50`). Todos os decimais aceitam até 10¹⁵, até 28
dígitos e até 12 casas decimais. Taxas são registradas sem alterar os cálculos atuais.

Datas em texto como `02/01/2024` são inválidas. O validador também aceita ISO com
horário à meia-noite e timestamps Unix (segundos ou milissegundos) que representem
meia-noite. Células de data/hora do XLSX perdem o horário na leitura. Prefira
`AAAA-MM-DD`. Fórmulas não são recalculadas: só o resultado armazenado no XLSX é lido.

Espaços nas extremidades dos valores são removidos. Campos opcionais vazios usam
os padrões da tabela. O limite é 5 MB por arquivo, 5.000 transações no CSV e 5.000
linhas após o cabeçalho no XLSX (incluindo linhas vazias intermediárias). XLSX tem
limite adicional de 25 MB descompactado.

### FX e modelo XLSX

Para BRL, o FX salvo é 1. Se informado, deve passar pela validação numérica antes
de ser substituído por 1. Para outra moeda sem FX, a prévia busca a taxa histórica
da liquidação; pode usar uma taxa anterior dentro da janela configurada. Sem taxa
disponível, a linha fica inválida. O FX resolvido é armazenado e não muda depois.
Liquidações futuras são aceitas em BRL ou com FX informado. A moeda é validada
apenas como três letras, sem garantia de cobertura pelo provedor. A moeda da
transação não altera a identidade canônica do instrumento: por exemplo, BTC
pode ter operações em BRL e USD.

`GET /api/transactions/import-template.xlsx` gera o download `modelo-transacoes.xlsx`
com `openpyxl`, já instalado. Não consulta banco ou provedor. O modelo inclui todos
os 13 cabeçalhos e três operações fictícias: compra/venda em BRL e compra em USD
com FX explícito. O teste de contrato baixa o arquivo e o valida no importador real.

## Verificação automática

```powershell
# Cálculos e leitores legados com dados sintéticos; testes de banco são ignorados por padrão.
.\.venv\Scripts\python.exe -m pytest -q

# Inclui testes com PostgreSQL. Eles usam transação externa e desfazem seus registros.
$env:RUN_DB_TESTS='1'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m alembic check
```

O teste manual do provedor de cotações faz uma chamada de rede real:

```powershell
.\.venv\Scripts\python.exe -m scripts.check_market_data
```

O histórico cambial usa Yahoo para FX e armazena tanto a PTAX de compra quanto a
PTAX de venda do boletim de fechamento do Banco Central. Ambas representam BRL por
unidade da moeda estrangeira. A camada de histórico devolve as duas observações sem
escolher qual se aplica; essa decisão pertence à futura regra tributária ou de negócio.
As variáveis `FX_RATE_PROVIDER`, `PTAX_RATE_PROVIDER` e
`RATE_FALLBACK_DAYS` podem ser definidas no `.env`; os valores suportados estão em
`.env.example`. Uma consulta busca primeiro no PostgreSQL e só chama o provedor se
a data necessária estiver ausente:

```text
GET /api/rates/FX/USD/2024-01-08
GET /api/rates/PTAX/USD/2024-01-08
```

Datas sem publicação usam a taxa anterior dentro do limite configurado, e a resposta
expõe a data efetivamente usada em `reference_date` e `fallback_used`. Para preencher
um intervalo de moedas usadas pela aplicação:

```json
POST /api/rates/backfill
{
  "currencies": ["USD", "EUR"],
  "rate_types": ["FX", "PTAX"],
  "start_date": "2024-01-01",
  "end_date": "2024-12-31"
}
```

O backfill apenas insere datas ausentes; valores históricos existentes não são
substituídos. A integração dessas taxas aos cálculos de carteira pertence ao suporte
multimoeda posterior.

Informe as moedas explicitamente no backfill; esse endpoint não seleciona as
moedas da carteira automaticamente.
Nos fins de semana, uma sexta-feira já armazenada pode ser reutilizada sem rede;
um cache mais antigo exige consultar o provedor antes de escolher a data anterior.
Falhas do provedor permitem usar o cache dentro do limite, mas falhas de gravação
cancelam a operação. A PTAX só aceita boletins de fechamento com compra e venda
válidas; boletins intradiários não são congelados como histórico definitivo.
No Yahoo, o dia corrente no fuso da série ainda pode mudar e só é armazenado
depois que o dia termina. Até lá, a consulta usa a taxa anterior disponível.

As cotações de ativos usam `MARKET_DATA_PROVIDER=yfinance` e
`MARKET_QUOTE_TTL_MINUTES=15` por padrão. O histórico diário do provedor é
compartilhado entre carteiras que usam o mesmo ticker e moeda. Intervalos já
consultados, inclusive feriados e fins de semana sem pregão, não são baixados
novamente. Cotações manuais continuam vinculadas somente ao ativo da carteira e
têm precedência sobre o valor compartilhado na mesma data. `GET` e `PUT` em
`/api/portfolios/{portfolio_id}/assets/{asset_id}/quote` consultam a cotação atual
e registram uma cotação manual, respectivamente.

A migração `0006` mantém as cotações existentes vinculadas ao ativo da carteira,
inclusive preços zero e a fonte original (`manual`, `legacy` ou `yfinance`).
O histórico Yahoo antigo usava preços ajustados e pode diferir entre carteiras;
somente novas consultas verificadas alimentam a base compartilhada. Datas de
consulta desconhecidas permanecem nulas, sem inventar cobertura de intervalos.

Para o teste real de navegador, tenha Microsoft Edge instalado e PostgreSQL ativo.
Compile o frontend; no primeiro terminal execute `scripts/start-browser-test.ps1`.
Ele usa o banco separado `portfolio_tracker_e2e` na porta HTTP 8001. No segundo:

```powershell
cd frontend
npm test
```

O teste cria dados fictícios somente nesse banco de teste. Capturas de tela ficam
em `frontend/test-results`. `Ctrl+C` encerra a API de testes.

## Limites mantidos e ajustes da migração

- Preço médio, ganho realizado e ganho não realizado preservam as fórmulas Buy/Sell.
- Taxas, dividendos e desdobramentos são registrados, sem aplicação financeira adicional.
- A variação diária é a variação do ganho; não é TWR ou retorno total com proventos.
- Quantidades, preços, taxas e câmbio das transações usam `Decimal`/`NUMERIC`;
  cotações históricas continuam no formato legado.
- Cotações ausentes aparecem como ausentes, e não como preço zero.
- Operações anteriores à primeira cotação são consideradas nessa primeira avaliação;
  a migração corrige esse desalinhamento de datas sem mudar a fórmula de ganho.
- Não há redesenho para titularidade, alocação ideal, aposentadoria ou múltiplos usuários.
- Mensagens UTF-8 devem ser lidas com `Get-Content -Encoding UTF8` no Windows PowerShell
  antigo. A exibição incorreta nesse terminal não significa corrupção no navegador.

## Backup

Use `pg_dump` em formato customizado, informando host, usuário e banco configurados
em `.env`; deixe a ferramenta solicitar a senha. Exemplo do banco local:

```powershell
.\.local\pgsql\bin\pg_dump.exe -h 127.0.0.1 -U portfolio -d portfolio_tracker -Fc -f .local/portfolio-backup.dump
```

Guarde uma cópia fora da pasta do projeto. Para testar restauração, use `pg_restore`
em um banco separado e vazio, nunca sobrescrevendo o banco em uso. Os arquivos antigos
foram preservados como fonte de conferência.
