import { useState } from 'react'
import { api, apiFile, type ImportPreview, type ImportPreviewRow } from './api'
import InstrumentPicker from './InstrumentPicker'
import { Link } from './navigation'
import { message, Modal } from './ui'

type Props = {
  portfolioId: number | null
  portfolioName: string
  busy: boolean
  mutate: (task: () => Promise<unknown>, success: string) => Promise<boolean>
}

// Documentation of src/transaction_import.py and TransactionInput; validation stays on the server.
const columns = [
  ['ticker', 'Obrigatória', 'Texto', '1–40 caracteres: letras A–Z/a–z, números e . ^ = : / _ -', 'FICTICIO-BR', 'Identificador do ativo; convertido para maiúsculas. Alias: asset.'],
  ['broker', 'Obrigatória', 'Texto', '1–120 caracteres', 'Corretora Fictícia', 'Corretora da operação.'],
  ['type', 'Obrigatória', 'Texto (operação)', 'Buy, Sell, Compra ou Venda', 'Buy', 'Aceita qualquer combinação de maiúsculas/minúsculas e remove espaços nas extremidades. Alias: transaction_type.'],
  ['trade_date', 'Obrigatória', 'Data', 'AAAA-MM-DD; célula de data no XLSX', '2024-01-02', 'Data da negociação, até hoje. Alias: trade date.'],
  ['settlement_date', 'Obrigatória', 'Data', 'AAAA-MM-DD; célula de data no XLSX', '2024-01-04', 'Igual ou posterior à negociação. Pode ser futura com BRL ou FX informado. Alias: settlement date.'],
  ['quantity', 'Obrigatória', 'Decimal', 'Maior que zero; ponto decimal', '10.5', 'Quantidade negociada.'],
  ['unit_price', 'Obrigatória', 'Decimal', 'Zero ou positivo; ponto decimal', '25.50', 'Preço unitário na moeda da transação. Aliases: price, unit price.'],
  ['transaction_currency', 'Condicional', 'Texto', 'Exatamente 3 letras A–Z/a–z', 'BRL', 'Obrigatória para cripto e ativos personalizados. Em ações/ETFs do catálogo, pode ser omitida e usa a moeda nativa; um valor diferente é rejeitado. Alias: currency.'],
  ['fx_rate', 'Opcional', 'Decimal', 'Maior que zero quando informado; ponto decimal', '5.25', 'BRL usa 1. Para moeda estrangeira, vazio busca FX histórico da liquidação. Alias: fx rate.'],
  ['allocation_class', 'Opcional', 'Texto', '1–120 caracteres quando informado', 'Exemplo', 'Vazio ou ausente: Sem classe. Alias: allocation class.'],
  ['brokerage_fee', 'Opcional', 'Decimal', 'Zero ou positivo; ponto decimal', '1.25', 'Vazio ou ausente: 0. Integra o custo de compra ou reduz o ganho de venda. Alias: brokerage fee.'],
  ['other_fees', 'Opcional', 'Decimal', 'Zero ou positivo; ponto decimal', '0.50', 'Vazio ou ausente: 0. Integram o custo de compra ou reduzem o ganho de venda. Alias: other fees.'],
  ['notes', 'Opcional', 'Texto', 'Até 5.000 caracteres', 'Exemplo fictício', 'Vazio ou ausente: texto vazio.'],
]

const dateLabel = (value: string) => value.split('-').reverse().join('/')
const columnName = (field: string) => ({ asset: 'ticker', price: 'unit_price', row: 'Linha' }[field] ?? field)

export default function TransactionImportPage(props: Props) {
  return <div className="transaction-import-page">
    <section className="panel" aria-labelledby="import-file-heading">
      <div className="section-heading"><div><h2 id="import-file-heading">Selecione e revise o arquivo</h2>
        <p>{props.portfolioId === null ? 'Crie ou selecione uma carteira para importar.' : <>Destino: <strong>{props.portfolioName}</strong>. Nenhuma transação é salva antes da confirmação.</>}</p>
      </div></div>
      <TransactionImporter {...props} />
    </section>
    <details className="panel import-guide"><summary className="section-heading">Modelo e instruções de importação</summary><section aria-labelledby="import-guide-heading">
      <div className="section-heading"><div><h2 id="import-guide-heading">Prepare sua planilha</h2><p>Baixe o modelo e substitua as três operações fictícias pelos seus registros.</p></div>
        <a className="button outline" href="/api/transactions/import-template.xlsx" download="modelo-transacoes.xlsx">Baixar planilha modelo</a>
      </div>
      <div className="import-instructions">
        <p><strong>Arquivo:</strong> CSV em UTF-8 (com ou sem BOM), separado por vírgula, ponto e vírgula ou tabulação; ou XLSX, usando a aba ativa. A primeira linha deve conter os cabeçalhos, sem título acima dela.</p>
        <p><strong>Limites:</strong> 5 MB por arquivo; até 5.000 transações no CSV. No XLSX, até 5.000 linhas após o cabeçalho, incluindo linhas vazias intermediárias, e 25 MB descompactados.</p>
        <p><strong>Cabeçalhos:</strong> a ordem é livre; maiúsculas/minúsculas e espaços nas extremidades são ignorados. Escolha um único nome por campo: nomes repetidos ou aliases do mesmo campo são rejeitados. Colunas desconhecidas são ignoradas; elas não substituem campos obrigatórios. Células excedentes sem cabeçalho são rejeitadas.</p>
        <p><strong>Números:</strong> em texto, use ponto decimal, como <code>1234.56</code>, sem símbolo de moeda nem separador de milhar. Vírgula decimal não é aceita. Células numéricas do Excel também são aceitas, mesmo que o Excel as exiba com vírgula. Para preservar muitos dígitos, formate a célula como texto antes de preencher.</p>
        <p>Todos os decimais têm limite de 1.000.000.000.000.000 (10¹⁵), até 28 dígitos e até 12 casas decimais. A leitura também aceita notação científica (<code>1e2</code>) e sublinhados (<code>1_000.50</code>). Não use fórmulas: o XLSX lê apenas o resultado armazenado pelo Excel e não recalcula.</p>
        <p>Role a tabela horizontalmente para consultar formatos, exemplos e observações de cada coluna.</p>
      </div>
      <div className="table-wrap" tabIndex={0} role="region" aria-label="Estrutura do arquivo, role horizontalmente para ver todas as colunas">
        <table className="import-spec" aria-label="Colunas aceitas pelo importador"><thead><tr>{['Coluna', 'Obrigatória / opcional', 'Tipo de dado', 'Formato / valores aceitos', 'Exemplo', 'Descrição / observações'].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead>
          <tbody>{columns.map(([name, required, type, format, example, notes]) => <tr key={name}><th scope="row"><code>{name}</code></th><td>{required}</td><td>{type}</td><td>{format}</td><td><code>{example}</code></td><td>{notes}</td></tr>)}</tbody>
        </table>
      </div>
      <div className="import-instructions">
        <h3>Datas e câmbio</h3>
        <p>Use datas como <code>2024-01-02</code>; texto como <code>02/01/2024</code> não é aceito. Por compatibilidade, o validador também aceita texto ISO com horário à meia-noite e timestamps Unix em segundos ou milissegundos que representem meia-noite. Células de data/hora do XLSX são convertidas para a data, descartando o horário.</p>
        <p>Deixe <code>fx_rate</code> vazio em BRL: o valor salvo será 1. Um valor informado precisa passar pela validação numérica antes de ser substituído por 1. Para moeda estrangeira, a prévia busca a taxa FX histórica da liquidação, usando a taxa anterior dentro da janela configurada quando necessário. Se não houver taxa disponível, a linha apresenta erro. O FX resolvido fica salvo e não muda com cotações futuras.</p>
        <p>A moeda é validada pelo formato de três letras; isso não garante que o provedor tenha histórico para ela. Valores opcionais vazios usam os padrões descritos na tabela. Espaços nas extremidades dos textos são removidos.</p>
        <h3>Revise antes de confirmar</h3>
        <p>Corrija as linhas indicadas na prévia ou no arquivo. A confirmação salva todas as linhas selecionadas em uma única operação e deixa a atualização da carteira pendente. A proteção de duplicatas usa o arquivo exato por carteira. Se importar apenas parte das linhas, as demais não poderão ser importadas reenviando o mesmo arquivo. Arquivos alterados não têm garantia de detecção como duplicado.</p>
      </div>
    </section></details>
  </div>
}

function TransactionImporter({ portfolioId, busy, mutate }: Props) {
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [result, setResult] = useState<{ imported: number; ignored: number } | null>(null)
  const [selected, setSelected] = useState<number[]>([])
  const [editing, setEditing] = useState<ImportPreviewRow | null>(null)
  const chosen = preview?.rows.filter(row => selected.includes(row.row)) ?? []
  const canConfirm = chosen.length > 0 && chosen.every(row => row.valid) && !preview?.already_imported
  const steps = ['Envio', 'Validação', 'Prévia e correção', 'Confirmação', 'Resultado']
  const currentStep = result ? 4 : confirming ? 3 : preview ? 2 : loading ? 1 : 0
  return <><ol className="import-steps" aria-label="Etapas de importação">{steps.map((label, index) => <li key={label} aria-current={index === currentStep ? 'step' : undefined}>{index + 1}. {label}</li>)}</ol><div className="import-box">
    <div><strong>Importar CSV/XLSX</strong><small>Selecione um arquivo de até 5 MB para conferir as operações.</small></div>
    <label className={'button outline file-select ' + (busy || loading || portfolioId === null ? 'disabled' : '')}>Selecionar arquivo<input className="sr-only" type="file" accept=".csv,.xlsx" disabled={busy || loading || portfolioId === null} onChange={async e => {
      const input = e.currentTarget
      const file = input.files?.[0]
      if (!file) return
      setLoading(true); setError(''); setPreview(null); setConfirming(false); setResult(null)
      try {
        const data = await apiFile<ImportPreview>('/portfolios/' + portfolioId + '/transactions/import-preview?filename=' + encodeURIComponent(file.name), file)
        setPreview(data); setSelected(data.rows.map(row => row.row))
      } catch (e) { setError(e instanceof Error ? e.message : 'Não foi possível ler o arquivo.') } finally { setLoading(false); input.value = '' }
    }} /></label>
    {loading && <span role="status">Validando…</span>}
    {error && <div role="alert" className="alert error import-error"><strong>Não foi possível validar o arquivo.</strong><p>{error}</p><p>Confira o formato e os cabeçalhos abaixo, corrija o arquivo e selecione-o novamente.</p></div>}
    {result && <section className="import-preview" aria-label="Resultado da importação"><h2>Importação concluída</h2><p role="status">{result.imported} importadas · {result.ignored} ignoradas · 0 duplicadas · 0 falhas.</p><Link className="button outline" href="/transactions">Ver transações</Link></section>}
    {preview && <div className="import-preview">
      <p role="status"><strong>{preview.filename}</strong>: {preview.rows.filter(row => row.valid).length} válida(s), {preview.rows.filter(row => !row.valid).length} inválida(s).</p>
      {preview.already_imported && <p role="alert" className="negative">Este arquivo já foi importado para esta carteira.</p>}
      <p>Total: {preview.rows.length} · Selecionadas: {chosen.length} · Duplicadas: {preview.already_imported ? preview.rows.length : 0} · Avisos: 0 · Erros: {preview.rows.filter(row => !row.valid).length}</p>
      {!confirming && <div className="table-wrap"><table aria-label="Selecionar e corrigir linhas"><thead><tr><th>Selecionar</th><th>Linha</th><th>Instrumento</th><th>Validação</th><th>Correção</th></tr></thead><tbody>{preview.rows.map(row => <tr key={row.row}><td><input type="checkbox" aria-label={'Selecionar linha ' + row.row} checked={selected.includes(row.row)} disabled={busy || preview.already_imported} onChange={e => setSelected(e.target.checked ? [...selected, row.row] : selected.filter(number => number !== row.row))} /></td><td>{row.row}</td><td>{row.data?.asset ?? row.raw?.asset}</td><td>{row.valid ? 'Válida' : 'Corrigir'}</td><td><button className="button quiet" disabled={busy || preview.already_imported} onClick={() => setEditing(row)}>Corrigir linha {row.row}</button></td></tr>)}</tbody></table></div>}
      {preview.rows.filter(row => row.data && ['unresolved', 'ambiguous'].includes(row.instrument_resolution ?? '')).map(row => <div key={row.row} className="panel">
        <strong>Linha {row.row}: resolver {row.data!.asset} ({row.instrument_resolution})</strong>
        <InstrumentPicker query={row.data!.asset} onSelect={async item => {
          try {
          const data = await api<NonNullable<typeof row.data>>('/portfolios/' + portfolioId + '/transactions/import-resolve', 'POST', {
            ...row.data, instrument_id: item.instrument_id,
          })
          setPreview(current => {
            if (!current) return current
            const rows = current.rows.map(value => value.row === row.row ? {
              ...value, data, valid: true, errors: [], instrument_resolution: 'resolved' as const,
            } : value)
            return { ...current, rows, valid: rows.every(value => value.valid) }
          })
          } catch (e) { setError(e instanceof Error ? e.message : 'Não foi possível resolver o instrumento.') }
        }} />
      </div>)}
      {!preview.valid && <div className="alert error" role="alert"><strong>Corrija as linhas abaixo na prévia ou no arquivo.</strong>
        <div className="table-wrap"><table aria-label="Erros de importação"><thead><tr><th>Linha</th><th>Coluna</th><th>Erro informado pelo validador</th></tr></thead><tbody>
          {preview.rows.filter(row => !row.valid).flatMap(row => row.errors.map((item, index) => <tr key={row.row + ':' + index}><td>{row.row}</td><td>{columnName(item.field)}</td><td>{item.message === 'Field required' ? 'Campo obrigatório ausente ou vazio.' : item.message}</td></tr>))}
        </tbody></table></div>
      </div>}
      {preview.rows.some(row => row.valid) && <div className="table-wrap" tabIndex={0} role="region" aria-label="Prévia, role horizontalmente para ver todas as colunas"><table aria-label="Prévia da importação"><thead><tr><th>Linha</th><th>Ativo / moeda</th><th>Operação</th><th>Negociação / liquidação</th><th>Corretora / classe</th><th>Quantidade</th><th>Preço / FX</th><th>Corretagem / outras taxas</th><th>Observações</th></tr></thead><tbody>
        {preview.rows.filter(row => row.valid && row.data).map(row => { const tx = row.data!; return <tr key={row.row}><td>{row.row}</td><td>{tx.asset}<small>{tx.transaction_currency}</small></td><td>{tx.type === 'Buy' ? 'Compra' : 'Venda'}</td><td>{dateLabel(tx.trade_date)}<small>{dateLabel(tx.settlement_date)}</small></td><td>{tx.broker}<small>{tx.allocation_class}</small></td><td>{tx.quantity}</td><td>{tx.price}<small>FX {tx.fx_rate}</small></td><td>{tx.brokerage_fee}<small>{tx.other_fees}</small></td><td>{tx.notes}</td></tr> })}
      </tbody></table></div>}
      <div className="form-footer"><span>{confirming ? 'Confirme as ' + chosen.length + ' linhas selecionadas. A proteção de duplicatas se aplica ao arquivo inteiro.' : 'Revise os valores antes de confirmar. Cabeçalhos e aliases são mapeados automaticamente.'}</span>{confirming && <button className="button outline" onClick={() => setConfirming(false)}>Voltar para prévia</button>}<button className="button primary" disabled={busy || loading || !canConfirm} onClick={async () => {
        if (!confirming) { setConfirming(true); return }
        const rows = chosen.map(row => row.data).filter((row): row is NonNullable<typeof row> => row !== undefined)
        let imported = rows.length
        if (await mutate(() => api('/portfolios/' + portfolioId + '/transactions/import', 'POST', {
          digest: preview.digest, filename: preview.filename, rows,
        }).then(value => { imported = (value as { imported: number }).imported; return value }), rows.length + ' transação(ões) importada(s). Atualização das posições pendente.')) { setResult({ imported, ignored: preview.rows.length - rows.length }); setPreview(null); setConfirming(false) }
      }}>{busy ? 'Importando…' : confirming ? 'Confirmar importação' : 'Revisar confirmação'}</button></div>
    </div>}
  </div>{editing && <Modal title={'Corrigir linha ' + editing.row} onClose={() => setEditing(null)}><ImportRowEditor row={editing} portfolioId={portfolioId!} onSaved={data => {
    setPreview(current => {
      if (!current) return current
      const rows = current.rows.map(row => row.row === editing.row ? { ...row, data, valid: true, errors: [], instrument_resolution: 'resolved' as const } : row)
      return { ...current, rows, valid: rows.every(row => row.valid) }
    }); setEditing(null)
  }} /></Modal>}</>
}

function ImportRowEditor({ row, portfolioId, onSaved }: { row: ImportPreviewRow; portfolioId: number; onSaved: (data: NonNullable<ImportPreviewRow['data']>) => void }) {
  const [draft, setDraft] = useState<Record<string, string>>(() => Object.fromEntries(Object.entries(row.data ?? row.raw ?? {}).map(([key, value]) => [key, value == null ? '' : String(value)])))
  const [instrumentId, setInstrumentId] = useState(row.data?.instrument_id ?? null), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  return <form onSubmit={async e => {
    e.preventDefault(); setBusy(true); setError('')
    try {
      const values = Object.fromEntries(Object.entries(draft).filter(([, value]) => value !== ''))
      onSaved(await api('/portfolios/' + portfolioId + '/transactions/import-resolve', 'POST', { ...values, instrument_id: instrumentId }))
    } catch (e) { setError(message(e)) } finally { setBusy(false) }
  }}><fieldset disabled={busy}><div className="form-grid">{[['asset', 'Instrumento'], ['type', 'Operação (Buy/Sell)'], ['trade_date', 'Negociação'], ['settlement_date', 'Liquidação'], ['broker', 'Corretora'], ['quantity', 'Quantidade'], ['price', 'Preço unitário'], ['transaction_currency', 'Moeda'], ['fx_rate', 'FX'], ['allocation_class', 'Classe'], ['brokerage_fee', 'Corretagem'], ['other_fees', 'Outras taxas'], ['notes', 'Observações']].map(([key, label]) => <label key={key}>{label}<input value={draft[key] ?? ''} onChange={e => { setDraft({ ...draft, [key]: e.target.value }); if (key === 'asset') setInstrumentId(null) }} /></label>)}</div>
  {!instrumentId && <InstrumentPicker query={draft.asset ?? ''} onSelect={item => { setInstrumentId(item.instrument_id); setDraft(current => ({ ...current, asset: item.symbol })) }} />}{error && <p role="alert">{error}</p>}<button className="button primary" disabled={!instrumentId}>{busy ? 'Validando…' : 'Validar correção'}</button></fieldset></form>
}
