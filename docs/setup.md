# Executar e testar o Portfolio Tracker

## Neste computador: um terminal no VS Code

Abra a pasta do projeto e **Terminal → Novo Terminal**. Na raiz, execute:

```powershell
.\scripts\start-local.ps1 -SkipBuild
```

Abra **http://127.0.0.1:8000**. Esse comando inicia o PostgreSQL portátil preparado
em `.local`, verifica o banco, aplica migrações pendentes e serve a API e a interface
React compilada no mesmo endereço. Não limpa nem reinicializa o banco.

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

## Desenvolvimento com atualização automática

Com PostgreSQL ativo, abra dois terminais na raiz:

```powershell
# Terminal 1: API
.\.venv\Scripts\python.exe -m alembic upgrade head
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

As planilhas Excel e o backup Money Manager não fazem parte desta migração técnica.
Seu importador com conciliação permanece no roadmap.

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

Informe as moedas explicitamente no backfill: o modelo atual de transações ainda
não registra moeda e não permite inferir uma lista confiável por carteira.
Nos fins de semana, uma sexta-feira já armazenada pode ser reutilizada sem rede;
um cache mais antigo exige consultar o provedor antes de escolher a data anterior.
Falhas do provedor permitem usar o cache dentro do limite, mas falhas de gravação
cancelam a operação. A PTAX só aceita boletins de fechamento com compra e venda
válidas; boletins intradiários não são congelados como histórico definitivo.
No Yahoo, o dia corrente no fuso da série ainda pode mudar e só é armazenado
depois que o dia termina. Até lá, a consulta usa a taxa anterior disponível.

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
- A precisão numérica continua em `float`, conforme o código original.
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
