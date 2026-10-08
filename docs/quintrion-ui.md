# Quintrion: navegação e contratos da interface

A interface da issue #41 usa o shell autenticado da #34. Espaço financeiro
(`Household` internamente) delimita privacidade e permissões; carteira delimita
investimentos e moeda de exibição. O seletor de espaço aparece apenas para quem
participa de mais de um espaço. Configurações de espaços continuam acessíveis a todos.

| Área | Rotas | Dados e ações existentes |
| --- | --- | --- |
| Visão geral | `/overview` | Overview, histórico consolidado, posições e atividade de mercado/renda fixa |
| Posições e detalhes | `/positions`, `/positions/:assetId`, `/fixed-income/:lotId` | Projeções, histórico por ativo, contratos e movimentos; edição sempre na fonte |
| Transações | `/transactions`, `/transactions/:id` | Transações e movimentos, edição/exclusão, FX salvo, consulta PTAX |
| Importação | `/transactions/import` | CSV/XLSX, prévia, resolução/correção validada no servidor, seleção, confirmação e resultado |
| Desempenho | `/performance` | Histórico da carteira; `/analytics` resume retornos diários existentes e fluxos na moeda de exibição |
| Dados de mercado | `/data/status`, `/data/quotes`, `/data/fx`, `/data/benchmarks`, `/data/corporate-actions` | Cobertura, preços manuais/provedor, câmbio/PTAX, CDI/IPCA, eventos e atividade |
| Instrumentos | `/instruments`, `/instruments/:id` | Identidade, aliases, mapeamentos, catálogo e instrumentos privados filtrados pelo espaço ativo |
| Carteiras | `/portfolios`, `/portfolios/new`, `/portfolios/:id/settings` | Criação, nome/moeda, total e status; sem permissões individuais de carteira |
| Espaços | `/settings/spaces`, `/settings/spaces/new`, `/settings/spaces/:id`, `/settings/spaces/:id/members` | Criação/nome, membros, papéis e convites; administração somente OWNER |
| Conta | `/account/profile`, `/account/security`, `/account/preferences`, `/account/data` | Identidades, vincular Google, tema persistido neste navegador |
| Acesso | `/login`, `/signup`, `/forgot-password`, `/reset-password`, `/invite/:token` | Google, login local de desenvolvimento e aceitação autenticada de convite |

`/` abre Visão geral. Links antigos com `#/...`, `/quotes`, `/catalog` e `/settings`
continuam reconhecidos. Em produção, o FastAPI serve o HTML nas rotas da interface;
APIs e arquivos ausentes preservam 404. O build deve preceder o início da API.

**Atualizar carteira** chama a consolidação existente, que busca os dados necessários
para preços, câmbio e benchmarks e reconstrói as projeções. Durante a operação a
interface bloqueia novas mutações; falhas e resultados parciais levam ao status dos
dados. Nenhuma nova regra tributária ou de precificação foi introduzida.

O retorno de período encadeia os retornos diários já calculados. Aportes líquidos
somam os fluxos da moeda de exibição. Lacunas, fontes pendentes e valores desconhecidos
permanecem indisponíveis. Custos contábeis nativos não são alterados pela moeda de exibição.

O resultado monetário do período usa o mesmo numerador dos retornos diários:
valor final + renda bruta do dia − valor inicial − fluxo líquido. Compras/aportes
adicionam capital; vendas/resgates removem os recursos líquidos. Taxas, renda fixa
e conversão cambial seguem as projeções existentes. Visão geral e Desempenho
compartilham os limites de calendário dos períodos. A API de analytics identifica
as datas solicitadas e as datas de fechamento avaliadas; o dia atual fica fora do
histórico. Sem abertura válida, fechamento necessário, FX ou fontes consolidadas,
o resultado permanece desconhecido.

Convites têm prévia autenticada do espaço, remetente, email, papel, estado e
expiração. Aceitar e rejeitar exigem identidade verificada correspondente ao email.
A migração `0027` registra remetente e decisão, incluindo rejeição persistente;
convites antigos preservam metadados de auditoria desconhecidos. Aceitar concede
somente a associação ao espaço existente. Expiração é derivada do prazo enquanto
o convite está pendente; aceitação, rejeição e revogação são estados terminais.

`/data/fx` mostra pares FX necessários, histórico armazenado de FX/PTAX, datas
necessárias, referências reutilizadas e lacunas. `/data/status` resume essas
lacunas por par e intervalo. As taxas congeladas nas transações continuam sendo
utilizadas conforme as regras existentes, sem exigir uma observação global que
não participa do cálculo. Necessidades de posições não consolidadas são provisórias.
Datas de observação e horários de consulta são distintos: não existe registro
de término de uma sincronização cambial completa, portanto esse horário é
explicitamente não registrado. Consulta avançada por data e a API de backfill
continuam disponíveis; a inspeção da cobertura não busca dados no provedor.

A lista de espaços recebe contagens de membros/carteiras agregadas no servidor,
papel e estado `ACTIVE`. Consulta a projeção completa ao abrir a lista, evitando
contagens antigas após criar carteiras e sem consultas individuais por espaço.

A importação mantém decimais textuais e a confirmação atômica existente. A proteção
contra duplicatas identifica o arquivo inteiro por digest: importar somente uma seleção
também marca esse arquivo como importado. Não há detecção de duplicatas por linha.
A correção usa o mesmo validador do servidor antes de permitir confirmação.

## Limitações identificadas antes da implementação

O backend atual não fornece cadastro/senha local de produção, Apple, recuperação de
senha, edição de perfil/avatar, dispositivos/MFA, exportação/exclusão de conta,
arquivamento/exclusão de carteira/espaço, origem e auditoria
por transação, exclusão de preço manual, correção manual de câmbio ou estados de
aprovação/rejeição de eventos. Esses controles não simulam sucesso. Preços manuais
podem ser corrigidos salvando novamente a mesma data. Eventos expõem suas fontes e
atividade, sem inventar estados de aprovação.

Overview compara o retorno com CDI armazenado para carteiras BRL; cobertura
ausente permanece incompleta. IBOV, SPX e taxa de caixa USD ficam indisponíveis
até existir uma projeção suportada. Desempenho mantém sua experiência anterior.
Valores convertidos por corretora não têm projeção pronta; a página mostra
quantidades por corretora e permite inspecionar CDI/IPCA separadamente.
Valores de renda fixa são brutos antes de impostos. O backend expõe retorno por
instrumento agregado, mas não retorno percentual individual do lote; esse campo
permanece indisponível no detalhe contratual.

## Overview — visual pass

O gráfico interativo alterna rentabilidade/patrimônio e usa datas compartilhadas
com Desempenho. O navigator, arraste, Ctrl + rolagem e Ctrl + Shift + rolagem
selecionam a janela; datas editáveis e tabela oferecem acesso por teclado.
`/analytics?include_series=true&benchmark_codes=CDI` acrescenta a série de retornos
diários encadeados e anualização em base de 365 dias sobre a cobertura efetiva.
CDI usa somente observações existentes e o calendário BR já suportado, sem chamada
de provedor. A API aceita códigos separados por vírgula para futura extensão;
códigos não suportados retornam estado explícito. A resposta padrão é preservada.

As três métricas principais são patrimônio atual, rentabilidade anualizada da
janela e ganho patrimonial (padrão 1M). O patrimônio mostra também o resultado
monetário do mês calendário, considerando somente dias encerrados. A alocação
agrupa valores na moeda de exibição fornecidos pelo backend; dados incompletos
não geram percentuais ou um donut de falsa cobertura. As cinco últimas atividades
mantêm data e valor bruto na moeda original. Horários não existentes no ledger
não são inventados. A última atualização feita nesta sessão pode exibir data/hora;
após recarregar, o cabeçalho informa apenas a data efetiva do histórico.

Restaurar um período personalizado retorna às datas originais desse período;
editar as datas após zoom mantém o gráfico e as métricas na mesma janela.
O CDI considera todas as observações de dias úteis entre as datas exibidas,
mesmo quando faltam snapshots da carteira; uma observação necessária ausente
mantém o retorno desconhecido. Em **Mais sobre a carteira**, a lista de cinco
maiores posições ordena os valores disponíveis na moeda de exibição e informa
quando há valores desconhecidos que impedem uma ordenação completa.

## Identidade e compatibilidade

Os arquivos em `frontend/public/brand` são cópias intactas do pacote vetorial canônico
fornecido com a issue. Os hashes SHA-256 são verificados em `tests/test_brand_identity.py`.
Manrope e Inter são servidos localmente, via Fontsource. `theme.css` concentra os tokens
Quintrion e os estados claro/escuro/sistema; `text.ts` estrutura navegação, ações e enums
visíveis. Conteúdo específico permanece nos componentes de cada página em pt-BR.

Nomes antigos mantidos intencionalmente: URL/nome do repositório `Portfolio-Tracker`,
bancos/volumes locais de instalações existentes, migrations aplicadas, cookies
`aurion_session`/`aurion_challenge`, cabeçalho `X-Aurion-Request` e leitura de migração
local do seletor `aurion-household`. Renomear esses contratos quebraria sessões,
integrações ou instalações; eles não são apresentados como marca na interface.

## Verificação manual

Use dados fictícios em carteira separada. Confira login Google real; navegação por
teclado e modais; posições em BRL e moeda estrangeira; renda fixa com aportes/resgates;
importação com linhas corrigidas e seleção; atualização com provedor real; alternância
de espaços/papéis; viewport móvel e tema escuro. Testes de navegador incluem fluxos
reais contra base de teste e cenários sintéticos de permissões/dados incompletos.
