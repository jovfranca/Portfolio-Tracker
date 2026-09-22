"""Import original transaction pickle without loading arbitrary Python globals."""
import argparse
import hashlib
import io
import json
import pickle
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from sqlalchemy import select
from src.database import SessionLocal
from src.models import Portfolio, Transaction, LegacyImport
from src.market_prices import save_user_price
from src.schemas import TransactionInput, QuoteInput
from src.services import get_portfolio, ensure_asset, ensure_asset_currency, get_overview, transaction_values
from src.instruments import create_instrument, resolve_instrument


def _legacy_instrument(session, identifier, currency='BRL'):
    resolution = resolve_instrument(session, identifier, currency=currency)
    if resolution.status == 'resolved':
        return resolution.instrument
    if resolution.status == 'ambiguous':
        raise ValueError(f'Identificador legado ambíguo: {identifier}.')
    return create_instrument(
        session, symbol=identifier, currency=currency,
        aliases=[identifier], alias_source='legacy', origin='MIGRATED',
    )


class LegacyTransaction:
    pass


class LegacyAsset:
    pass


def read_limited(path, message):
    path = Path(path)
    if path.stat().st_size > 20_000_000:
        raise ValueError(message)
    return path.read_bytes()


class AssetReader(pickle.Unpickler):
    """Allow only the concrete pandas/numpy types used in the original cache.

    CLI-only compatibility reader; never expose pickle uploads through the API.
    """
    def find_class(self, module, name):
        if module == 'src.models.asset' and name == 'Asset':
            return LegacyAsset
        allowed = {
            ('numpy.core.multiarray', 'scalar'), ('numpy.core.multiarray', '_reconstruct'),
            ('numpy._core.multiarray', '_reconstruct'), ('numpy._core.numeric', '_frombuffer'),
            ('numpy', 'dtype'), ('numpy', 'ndarray'), ('builtins', 'slice'),
            ('pandas', 'DataFrame'), ('pandas.core.frame', 'DataFrame'),
            ('pandas.core.internals.managers', 'BlockManager'),
            ('pandas._libs.internals', '_unpickle_block'), ('pandas.core.indexes.base', '_new_Index'),
            ('pandas', 'Index'), ('pandas.core.indexes.base', 'Index'),
            ('pandas.core.indexes.datetimes', '_new_DatetimeIndex'),
            ('pandas.core.indexes.datetimes', 'DatetimeIndex'), ('pandas._libs.arrays', '__pyx_unpickle_NDArrayBacked'),
            ('pandas.core.arrays.datetimes', 'DatetimeArray'), ('pandas.core.dtypes.dtypes', 'DatetimeTZDtype'),
            ('pandas', 'DatetimeIndex'), ('pandas', 'StringDtype'),
            ('pandas', 'DatetimeTZDtype'), ('pandas.arrays', 'StringArray'),
            ('pandas.arrays', 'DatetimeArray'), ('datetime', 'timezone'),
            ('datetime', 'timedelta'), ('pytz', '_p'),
        }
        if (module, name) not in allowed:
            raise pickle.UnpicklingError('Tipo não permitido no cache de ativos.')
        if module == 'numpy.core.multiarray':
            module = 'numpy._core.multiarray'
        return super().find_class(module, name)


def read_assets(path):
    data = read_limited(path, 'Cache excede 20 MB.')
    records = AssetReader(io.BytesIO(data)).load()
    if not isinstance(records, list) or not all(isinstance(a, LegacyAsset) for a in records):
        raise ValueError('Cache de ativos inválido.')
    result = []
    for asset in records:
        quotes = [QuoteInput(
                             date=index.date(),
                             close=Decimal(str(float(row['Close']))).quantize(Decimal('0.000000000001')),
                             dividends=float(row['Dividends']), stock_splits=float(row['Stock Splits']))
                  for index, row in asset.history.iterrows()]
        result.append((asset, quotes))
    return result


class TransactionReader(pickle.Unpickler):
    def find_class(self, module, name):
        if name == 'Transaction' and module in {
            'src.models.transaction', 'models.transaction',
            'src.archive.old_models.transaction', 'src.archive.OLD_models.transaction',
        }:
            return LegacyTransaction
        raise pickle.UnpicklingError('Tipo não permitido no arquivo de transações.')


def read_transactions(path):
    data = read_limited(path, 'Arquivo excede o limite de 20 MB.')
    records = TransactionReader(io.BytesIO(data)).load()
    if not isinstance(records, list) or not all(isinstance(t, LegacyTransaction) for t in records):
        raise ValueError('O arquivo deve conter uma lista de transações do projeto original.')
    validated = []
    for transaction in records:
        timestamp = transaction.date_time
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        values = {
            key: getattr(transaction, key)
            for key in TransactionInput.model_fields
            if hasattr(transaction, key)
        }
        values.update({
            'trade_date': timestamp.date(),
            'settlement_date': timestamp.date(),
            'asset_currency': 'BRL',
            'fx_rate': 1,
        })
        if timestamp.tzinfo is not None:
            raise ValueError('Use data/hora local sem fuso, como no histórico original.')
        validated.append((timestamp, TransactionInput.model_validate(values)))
    return hashlib.sha256(data).hexdigest(), [
        record for _, record in sorted(validated, key=lambda item: item[0])
    ]


def import_transactions(session, path, portfolio_id, assets_path=None):
    digest, records = read_transactions(path)
    get_portfolio(session, portfolio_id, lock=True)
    previous = session.scalar(select(LegacyImport).where(
        LegacyImport.portfolio_id == portfolio_id, LegacyImport.digest == digest))
    if previous:
        return {'imported': 0, 'already_imported': True}
    if session.scalar(select(Transaction.id).where(Transaction.portfolio_id == portfolio_id).limit(1)):
        raise ValueError('Escolha uma carteira vazia para a migração inicial. Mesclar históricos exige conciliação.')
    for record in records:
        instrument = _legacy_instrument(session, record.asset, record.asset_currency)
        ensure_asset_currency(session, portfolio_id, instrument.id, record.asset_currency)
        ensure_asset(session, portfolio_id, instrument)
        values = transaction_values(session, record)
        values['instrument_id'] = instrument.id
        session.add(Transaction(
            portfolio_id=portfolio_id, **values
        ))
    if assets_path:
        for old, quotes in read_assets(assets_path):
            instrument = _legacy_instrument(session, old.ticker.upper())
            asset = ensure_asset(session, portfolio_id, instrument)
            for field in ['asset_class', 'sector', 'sub_sector']:
                setattr(asset, field, getattr(old, field, '') or '')
            for quote in quotes:
                stored = save_user_price(
                    session, asset, quote.date, quote.close, quote.currency or 'BRL',
                    quote.dividends, quote.stock_splits,
                )
                stored.source = 'legacy'
                stored.retrieved_at = None
    session.flush()
    get_overview(session, portfolio_id)
    session.add(LegacyImport(portfolio_id=portfolio_id, digest=digest, records=len(records)))
    session.flush()
    return {'imported': len(records), 'already_imported': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--portfolio-id', type=int)
    parser.add_argument('--name', default='Carteira migrada')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--assets', type=Path, help='Cache assets.pkl original, opcional.')
    args = parser.parse_args()
    if args.dry_run:
        _, records = read_transactions(args.path)
        cached = read_assets(args.assets) if args.assets else []
        print(json.dumps({'valid_transactions': len(records), 'cached_assets': len(cached),
                          'cached_quotes': sum(len(quotes) for _, quotes in cached)}))
        return
    with SessionLocal.begin() as session:
        portfolio_id = args.portfolio_id
        if portfolio_id is None:
            digest, _ = read_transactions(args.path)
            previous = session.scalar(select(LegacyImport).where(LegacyImport.digest == digest))
            if previous:
                print(json.dumps({'imported': 0, 'already_imported': True, 'portfolio_id': previous.portfolio_id}))
                return
            p = Portfolio(name=args.name)
            session.add(p)
            session.flush()
            portfolio_id = p.id
        result = import_transactions(session, args.path, portfolio_id, args.assets)
    print(json.dumps(result | {'portfolio_id': portfolio_id}))


if __name__ == '__main__':
    main()
