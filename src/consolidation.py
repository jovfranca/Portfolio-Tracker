"""Consolidate canonical positions and project dated reporting values."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import delete, event, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.corporate_actions import get_actions, get_stored_actions
from src.domain import ZERO, portfolio_day, position_history, position_now, project_position_history
from src.market_prices import get_history, get_latest, get_quote_history, history_for_reporting, stored_price_gaps
from src.models import (
    Asset, BenchmarkObservation, CorporateAction, CorporateActionCoverage, FixedIncomeLot,
    Portfolio, PortfolioSnapshot, PositionInvalidation, PositionSnapshot, Transaction,
    UserCorporateEvent,
)
from src.position_reporting import historical_valuation_factors, reporting_factors, sources
from src.rates import RateUnavailable, backfill_rates, convert_amount


POSITION_FIELDS = (
    'quantity', 'remaining_acquisition_cost', 'average_cost', 'market_value',
    'realized_gain', 'unrealized_gain', 'gross_income', 'total_gain',
    'net_flow', 'purchases', 'daily_income', 'daily_return_pct', 'cumulative_return_pct',
)
CANONICAL_CURRENCY = 'BRL'
PORTFOLIO_FIELDS = (
    'remaining_acquisition_cost', 'market_value', 'realized_gain',
    'unrealized_gain', 'gross_income', 'total_gain',
)


def mark_dirty(session, portfolio_id, day, instrument_id, reason='source'):
    """Keep the earliest affected date for each position and the portfolio banner."""
    portfolio = session.get(Portfolio, portfolio_id)
    if portfolio is not None:
        portfolio.dirty_from = min(portfolio.dirty_from, day) if portfolio.dirty_from else day
    invalidation = next((row for row in session.new if isinstance(row, PositionInvalidation)
                         and row.portfolio_id == portfolio_id and row.instrument_id == instrument_id), None)
    if invalidation is None:
        with session.no_autoflush:
            invalidation = session.scalar(select(PositionInvalidation).where(
                PositionInvalidation.portfolio_id == portfolio_id,
                PositionInvalidation.instrument_id == instrument_id,
            ))
    if invalidation is None:
        session.add(PositionInvalidation(portfolio_id=portfolio_id, instrument_id=instrument_id,
                                         dirty_from=day, reason=reason))
    elif day < invalidation.dirty_from:
        invalidation.dirty_from = day
        invalidation.reason = reason


@event.listens_for(Session, 'before_flush')
def invalidate_changed_inputs(session, flush_context, instances):
    """Catch API, import and provider writes in one place, including old edit dates."""
    affected = {}

    def add(portfolio_id, instrument_id, day, reason='source'):
        if portfolio_id is not None and instrument_id is not None and day is not None:
            key = (portfolio_id, instrument_id)
            affected[key] = (min(affected[key][0], day), reason) if key in affected else (day, reason)

    def old_day(obj, field):
        history = inspect(obj).attrs[field].history
        return min([getattr(obj, field)] + list(history.deleted))

    for obj in set(session.new) | set(session.dirty) | set(session.deleted):
        if isinstance(obj, Transaction):
            day = old_day(obj, 'trade_date')
            add(obj.portfolio_id, obj.instrument_id, day, 'transaction')
            for previous_id in inspect(obj).attrs.instrument_id.history.deleted:
                add(obj.portfolio_id, previous_id, day, 'transaction')
        elif isinstance(obj, UserCorporateEvent):
            asset = session.get(Asset, obj.asset_id)
            if asset is not None:
                add(asset.portfolio_id, asset.instrument_id, old_day(obj, 'effective_date'), 'event')
        elif isinstance(obj, (CorporateAction, CorporateActionCoverage)):
            if isinstance(obj, CorporateActionCoverage) and obj.is_final is False:
                # A TTL refresh of today's coverage changes no finalized daily
                # snapshot. Any newly discovered event invalidates itself.
                continue
            instrument_id = obj.instrument_id
            day = old_day(obj, 'effective_date' if isinstance(obj, CorporateAction) else 'start_date')
            instrument_ids = {instrument_id, *inspect(obj).attrs.instrument_id.history.deleted}
            for affected_instrument_id in instrument_ids - {None}:
                for portfolio_id in session.scalars(select(Asset.portfolio_id).where(
                    Asset.instrument_id == affected_instrument_id).distinct()):
                    add(portfolio_id, affected_instrument_id, day, 'event')
        elif isinstance(obj, BenchmarkObservation):
            connection = session.connection()
            translated_schema = connection.get_execution_options().get('schema_translate_map', {}).get(None)
            if inspect(connection).has_table('fixed_income_lots', schema=translated_schema):
                for portfolio_id, instrument_id, start_date in session.execute(select(
                        Asset.portfolio_id, Asset.instrument_id, FixedIncomeLot.start_date).join(
                        FixedIncomeLot, FixedIncomeLot.asset_id == Asset.id).where(
                        FixedIncomeLot.benchmark_id == obj.benchmark_id)):
                    add(portfolio_id, instrument_id, start_date, 'benchmark')
    for (portfolio_id, instrument_id), (day, reason) in affected.items():
        mark_dirty(session, portfolio_id, day, instrument_id, reason)


def _position_values(snapshot):
    return {
        'date': snapshot.date, 'reporting_currency': snapshot.reporting_currency,
        'status': snapshot.status,
        'quote_date': snapshot.quote_date,
        **{field: getattr(snapshot, field) for field in POSITION_FIELDS},
    }


def position_series(session, portfolio_id, instrument_id, *, include_state=False):
    from src.services import get_portfolio
    portfolio = get_portfolio(session, portfolio_id)
    from src.fixed_income import daily_position_rows, list_lots
    lots = [lot for lot in list_lots(session, portfolio_id)
            if lot.asset.instrument_id == instrument_id]
    if lots:
        start = min(lot.start_date for lot in lots)
        through = portfolio.history_built_through
        dirty_from = session.scalar(select(PositionInvalidation.dirty_from).where(
            PositionInvalidation.portfolio_id == portfolio_id,
            PositionInvalidation.instrument_id == instrument_id,
        ))
        result = []
        day = start
        previous_value = ZERO
        factor = Decimal('1')
        while through is not None and day <= through:
            if dirty_from is not None and day >= dirty_from:
                result.append({
                    'date': day, 'reporting_currency': portfolio.display_currency,
                    'status': 'pending', 'quote_date': None,
                    **{field: None for field in POSITION_FIELDS},
                })
                day += timedelta(days=1)
                continue
            row = daily_position_rows(session, lots, day, portfolio.display_currency)[0]
            denominator = (previous_value + row.purchases
                           if previous_value is not None and row.purchases is not None else None)
            if (row.status == 'complete' and row.market_value is not None and
                    previous_value is not None and row.net_flow is not None and
                    denominator is not None and denominator > 0 and factor is not None):
                daily_return = (row.market_value - previous_value - row.net_flow) / denominator
                factor *= 1 + daily_return
            elif row.status == 'complete' and row.market_value == previous_value == ZERO:
                daily_return = ZERO
            else:
                daily_return = factor = None
            status = ('incomplete_history' if row.status == 'complete' and factor is None
                      else row.status)
            result.append({
                'date': day, 'reporting_currency': portfolio.display_currency,
                'status': status, 'quote_date': None, 'quantity': None,
                'remaining_acquisition_cost': row.remaining_acquisition_cost,
                'average_cost': None, 'market_value': row.market_value,
                'realized_gain': row.realized_gain, 'unrealized_gain': row.unrealized_gain,
                'gross_income': row.gross_income, 'total_gain': row.total_gain,
                'net_flow': row.net_flow, 'purchases': row.purchases,
                'daily_income': row.daily_income,
                'daily_return_pct': daily_return * 100 if daily_return is not None else None,
                'cumulative_return_pct': (factor - 1) * 100 if factor is not None else None,
            })
            previous_value = row.market_value
            day += timedelta(days=1)
        return result
    rows = list(session.scalars(select(PositionSnapshot).where(
        PositionSnapshot.portfolio_id == portfolio_id,
        PositionSnapshot.instrument_id == instrument_id,
        PositionSnapshot.reporting_currency == CANONICAL_CURRENCY,
    ).order_by(PositionSnapshot.date)))
    if not rows:
        return []
    asset = session.scalar(select(Asset).where(
        Asset.portfolio_id == portfolio_id, Asset.instrument_id == instrument_id,
    ))
    if asset is None:
        return []
    transactions = list(session.scalars(select(Transaction).where(
        Transaction.portfolio_id == portfolio_id,
        Transaction.instrument_id == instrument_id,
    )))
    events = get_stored_actions(session, asset, end=rows[-1].date)
    prices = [price for price in get_quote_history(session, asset) if price.date <= rows[-1].date]
    rates = reporting_factors(session, portfolio.display_currency, transactions, events, [])
    currencies = {price.currency for price in prices}
    rates.update(historical_valuation_factors(session, currencies, portfolio.display_currency,
                                              [row.date for row in rows]))
    price_gaps = stored_price_gaps(session, asset, rows[0].date, rows[-1].date)
    projected = project_position_history(rows, transactions, events, prices,
                                         portfolio.display_currency, rates, price_gaps,
                                         include_state=include_state)
    dirty_from = session.scalar(select(PositionInvalidation.dirty_from).where(
        PositionInvalidation.portfolio_id == portfolio_id,
        PositionInvalidation.instrument_id == instrument_id,
    ))
    result = []
    for canonical, item in zip(rows, projected):
        values = {key: value for key, value in item.items()
                  if key in ({'date', 'reporting_currency', 'status', 'quote_date', *POSITION_FIELDS,
                              'ledger_state'} if include_state else
                             {'date', 'reporting_currency', 'status', 'quote_date', *POSITION_FIELDS})}
        if dirty_from is not None and canonical.date >= dirty_from:
            # The changed source activity has not entered canonical history.
            # Keep previously consolidated accounting and flag the boundary.
            if portfolio.display_currency == CANONICAL_CURRENCY:
                values.update(_position_values(canonical))
            else:
                values.update({field: None for field in POSITION_FIELDS if field != 'quantity'})
                values['quantity'] = canonical.quantity
                values['reporting_currency'] = portfolio.display_currency
                values['market_value'] = item['market_value']
            values['status'] = 'pending'
        result.append(values)
    return result


def portfolio_series(session, portfolio_id):
    from src.services import get_portfolio
    from src.fixed_income import daily_position_rows, list_lots
    portfolio = get_portfolio(session, portfolio_id)
    first_lot_day = min((lot.start_date for lot in list_lots(session, portfolio_id)), default=None)
    first_pending_day = (max(first_lot_day, portfolio.dirty_from)
                         if first_lot_day is not None and portfolio.dirty_from is not None else None)
    if portfolio.history_built_through is None:
        return []
    instruments = list(session.scalars(select(PositionSnapshot.instrument_id).where(
        PositionSnapshot.portfolio_id == portfolio_id,
        PositionSnapshot.reporting_currency == CANONICAL_CURRENCY,
    ).distinct()))
    by_day = defaultdict(list)
    for instrument_id in instruments:
        for row in position_series(session, portfolio_id, instrument_id):
            by_day[row['date']].append(SimpleNamespace(**row))
    first = min([*by_day.keys(), *([first_lot_day] if first_lot_day else [])], default=None)
    if first is None:
        return []
    lots = list_lots(session, portfolio_id)
    result = []
    previous_value = ZERO
    factor = Decimal('1')
    day = first
    while day <= portfolio.history_built_through:
        daily_rows = by_day.get(day, []).copy()
        daily_rows.extend(daily_position_rows(session, lots, day, portfolio.display_currency))
        if daily_rows:
            values = portfolio_day(daily_rows, previous_value, factor)
            if values['status'] == 'complete' and values['cumulative_return_pct'] is None:
                values['status'] = 'incomplete_history'
            result.append(_pending_fixed_income_values({
                'date': day, 'reporting_currency': portfolio.display_currency,
                'quantity': None, 'average_cost': None,
                'status': values['status'],
                **{field: values[field] for field in PORTFOLIO_FIELDS},
                'daily_return_pct': values['daily_return_pct'],
                'cumulative_return_pct': values['cumulative_return_pct'],
            }, first_pending_day))
            previous_value, factor = values['market_value'], values['return_factor']
        day += timedelta(days=1)
    return result


def _pending_fixed_income_values(values, first_pending_day):
    """Do not present equity-only portfolio totals after a lot begins."""
    if first_pending_day is not None and values['date'] >= first_pending_day:
        values.update({field: None for field in (*PORTFOLIO_FIELDS,
                                                'daily_return_pct', 'cumulative_return_pct')})
        values['status'] = 'incomplete'
        if 'return_factor' in values:
            values['return_factor'] = None
    return values


def consolidate(session, portfolio_id):
    from src.services import get_portfolio
    from src.benchmarks import get_history as get_benchmark_history
    from src.fixed_income import daily_position_rows, list_lots, position_valuations
    portfolio = get_portfolio(session, portfolio_id, lock=True)
    all_lots = list_lots(session, portfolio_id)
    _, transactions, assets = sources(session, portfolio_id)
    invalidations = list(session.scalars(select(PositionInvalidation).where(
        PositionInvalidation.portfolio_id == portfolio_id)))
    dirty_by_instrument = {row.instrument_id: row.dirty_from for row in invalidations}
    # A new calendar day requires a suffix for every existing position.
    extend = portfolio.history_built_through is None or portfolio.history_built_through < date.today() - timedelta(days=1)
    selected_ids = ({asset.instrument_id for asset in assets} if extend else set(dirty_by_instrument))
    selected_assets = [asset for asset in assets if asset.instrument_id in selected_ids]
    pending_lots = [lot for lot in all_lots if lot.asset.instrument_id in selected_ids]
    if not transactions and not all_lots:
        session.execute(delete(PositionSnapshot).where(PositionSnapshot.portfolio_id == portfolio_id))
        session.execute(delete(PortfolioSnapshot).where(PortfolioSnapshot.portfolio_id == portfolio_id))
        session.execute(delete(PositionInvalidation).where(PositionInvalidation.portfolio_id == portfolio_id))
        portfolio.dirty_from = None
        portfolio.history_built_through = None
        session.flush()
        return {'complete': True,
                'history_status': 'complete',
                'recalculated_from': None, 'incomplete_assets': [],
                'snapshot_days': 0,
                'reasons': {}, 'message': 'Carteira consolidada.'}

    first_day = min([row.trade_date for row in transactions] + [lot.start_date for lot in all_lots])
    # Removing or moving the earliest trade advances the history boundary.
    # Rows before the new boundary cannot be derived from the remaining source.
    session.execute(delete(PositionSnapshot).where(
        PositionSnapshot.portfolio_id == portfolio_id,
        PositionSnapshot.date < first_day,
    ))
    session.execute(delete(PortfolioSnapshot).where(
        PortfolioSnapshot.portfolio_id == portfolio_id,
        PortfolioSnapshot.date < first_day,
    ))
    valuation_date = date.today()
    through = valuation_date - timedelta(days=1)
    # Valuation reads stored canonical observations; populate them with the
    # shared benchmark service before replaying portfolio history.
    for lot in pending_lots:
        if lot.benchmark is None or lot.start_date > through:
            continue
        if lot.yield_structure == 'BENCHMARK_SPREAD':
            first_month = lot.start_date.year * 12 + lot.start_date.month - 2 - lot.benchmark_lag_months
            last_month = through.year * 12 + through.month - 2 - lot.benchmark_lag_months
            first = date(first_month // 12, first_month % 12 + 1, 1)
            last = date(last_month // 12, last_month % 12 + 1, 1)
        else:
            first, last = lot.start_date, through
        if first <= last:
            get_benchmark_history(session, lot.benchmark.code, first, last)
    dirty = min(dirty_by_instrument.values(), default=None)
    start = max(first_day, dirty or (portfolio.history_built_through + timedelta(days=1)
                                     if portfolio.history_built_through else first_day))
    if portfolio.history_built_through is None:
        start = first_day
    if start > through:
        start = through + timedelta(days=1)
    incomplete = []
    history_incomplete = []
    problems = defaultdict(list)
    latest_by_instrument = {}
    action_gaps_by_instrument = {}
    price_gaps_by_instrument = {}
    by_instrument = defaultdict(list)
    for row in transactions:
        by_instrument[row.instrument_id].append(row)
    # Fetch all inputs first: provider inserts can move dirty_from backwards.
    # The replay boundary must be decided only after those inserts have flushed.
    fx_dates = defaultdict(set)
    fx_assets = defaultdict(set)
    for asset in selected_assets:
        if asset.instrument.asset_type == 'FIXED_INCOME':
            continue
        rows = by_instrument.get(asset.instrument_id, [])
        if not rows:
            continue
        asset_first = min(row.trade_date for row in rows)
        next_day = (portfolio.history_built_through + timedelta(days=1)
                    if portfolio.history_built_through else asset_first)
        fetch_start = max(asset_first, min(next_day, dirty_by_instrument.get(
            asset.instrument_id, next_day)))
        if asset_first <= through:
            # Establish a prior observation when the first trade has no close.
            history_result = get_history(session, asset, fetch_start - timedelta(days=30), through)
            # An opening-lookback failure is irrelevant once the holding period
            # itself is covered; genuine failed holding-period queries are not.
            price_gaps_by_instrument[asset.instrument_id] = [
                (max(fetch_start, first), last) for first, last in history_result.missing_ranges
                if last >= fetch_start]
            if price_gaps_by_instrument[asset.instrument_id]:
                incomplete.append(asset.instrument.symbol)
                problems[asset.instrument.symbol].append(
                    'histórico de cotações não retornado pelo provedor')
        action_result = get_actions(session, asset, fetch_start, valuation_date)
        action_gaps_by_instrument[asset.instrument_id] = action_result.missing_ranges
        if not action_result.complete:
            incomplete.append(asset.instrument.symbol)
            problems[asset.instrument.symbol].append('cobertura de eventos corporativos incompleta')
        if position_now(rows, get_stored_actions(session, asset), None,
                        CANONICAL_CURRENCY, {}, valuation_date=valuation_date)['quantity'] > 0:
            try:
                latest_by_instrument[asset.instrument_id] = get_latest(session, asset)
            except (ValueError, RuntimeError, OSError):
                latest_by_instrument[asset.instrument_id] = None
        events = get_stored_actions(session, asset)
        prices = history_for_reporting(session, asset)
        for price in prices:
            if fetch_start <= price.date <= date.today():
                fx_dates[price.currency].add(price.date)
                fx_dates[CANONICAL_CURRENCY].add(price.date)
                fx_assets[price.currency].add(asset.instrument.symbol)
                fx_assets[CANONICAL_CURRENCY].add(asset.instrument.symbol)
        # A carried price still needs valuation-day FX on every calendar day.
        valuation_currencies = {price.currency for price in prices} | {CANONICAL_CURRENCY}
        for currency in valuation_currencies:
            fx_dates[currency].update(fetch_start + timedelta(days=offset)
                                      for offset in range((valuation_date - fetch_start).days + 1))
            fx_assets[currency].add(asset.instrument.symbol)
        for event in events:
            if event.currency and event.effective_date <= date.today():
                fx_dates[event.currency].add(event.effective_date)
                fx_dates[CANONICAL_CURRENCY].add(event.effective_date)
                fx_assets[event.currency].add(asset.instrument.symbol)
                fx_assets[CANONICAL_CURRENCY].add(asset.instrument.symbol)
    for lot in pending_lots:
        if lot.start_date > valuation_date:
            continue
        for currency in {lot.currency, CANONICAL_CURRENCY, portfolio.display_currency}:
            fx_dates[currency].update(lot.start_date + timedelta(days=offset)
                                      for offset in range((valuation_date - lot.start_date).days + 1))
            fx_assets[currency].add(lot.asset.instrument.symbol)
    for currency, days in fx_dates.items():
        if currency in {'BRL', None}:
            continue
        missing = []
        for day in sorted(days):
            try:
                convert_amount(session, Decimal('1'), currency, 'BRL', day,
                               fetcher=lambda *_: [])
            except RateUnavailable:
                missing.append(day)
        if missing:
            try:
                backfill_rates(session, [currency], ['FX'], min(missing), max(missing))
            except SQLAlchemyError:
                raise
            except Exception:
                for symbol in fx_assets[currency]:
                    problems[symbol].append(f'consulta de câmbio {currency} indisponível')
    session.flush()
    dirty_by_instrument = {row.instrument_id: row.dirty_from for row in session.scalars(
        select(PositionInvalidation).where(PositionInvalidation.portfolio_id == portfolio_id))}
    if portfolio.dirty_from is not None:
        start = min(start, max(first_day, portfolio.dirty_from))
    for asset in selected_assets:
        if asset.instrument.asset_type == 'FIXED_INCOME':
            continue
        rows = by_instrument.get(asset.instrument_id, [])
        if not rows:
            session.execute(delete(PositionSnapshot).where(
                PositionSnapshot.portfolio_id == portfolio_id,
                PositionSnapshot.instrument_id == asset.instrument_id))
            continue
        events = get_stored_actions(session, asset)
        if position_now(rows, events, None, CANONICAL_CURRENCY, {},
                        valuation_date=valuation_date)['quantity'] > 0:
            try:
                # The shared quote service handles TTL and provider errors. One
                # failed asset never prevents the remaining portfolio from updating.
                latest = latest_by_instrument.get(asset.instrument_id)
                if latest is None or latest.price is None or latest.stale:
                    incomplete.append(asset.instrument.symbol)
                    problems[asset.instrument.symbol].append(
                        'cotação atual indisponível ou desatualizada')
            except (ValueError, RuntimeError, OSError):
                incomplete.append(asset.instrument.symbol)
                problems[asset.instrument.symbol].append('falha ao consultar a cotação atual')
        prices = history_for_reporting(session, asset)
        if prices and prices[-1].currency != CANONICAL_CURRENCY:
            try:
                convert_amount(session, Decimal('1'), prices[-1].currency,
                               CANONICAL_CURRENCY, valuation_date)
            except RateUnavailable:
                if asset.instrument.symbol not in incomplete:
                    incomplete.append(asset.instrument.symbol)
                problems[asset.instrument.symbol].append('câmbio da cotação atual indisponível')
        # Today's trades/events are outside finalized snapshots. Validate their
        # current ledger too, including settlement FX and corporate income FX.
        current_prices = [price for price in prices if price.date <= valuation_date]
        current_quote = current_prices[-1] if current_prices else None
        current_rates = reporting_factors(
            session, CANONICAL_CURRENCY, rows, events,
            [current_quote] if current_quote else [], valuation_date=valuation_date,
        )
        current = position_now(
            rows, events, current_quote, CANONICAL_CURRENCY, current_rates,
            valuation_date=valuation_date,
            actions_complete=not action_gaps_by_instrument.get(asset.instrument_id),
        )
        if current['status'] != 'complete':
            incomplete.append(asset.instrument.symbol)
            current_reason = {
                'missing_fx': 'câmbio ausente',
                'missing_price': 'cotação ausente',
                'missing_price_and_fx': 'cotação e câmbio ausentes',
                'missing_actions': 'cobertura de eventos corporativos incompleta',
            }.get(current['status'], 'dados incompletos')
            problems[asset.instrument.symbol].append(
                'posição atual incompleta: ' + current_reason)
        next_day = (portfolio.history_built_through + timedelta(days=1)
                    if portfolio.history_built_through else min(row.trade_date for row in rows))
        instrument_start = min(next_day, dirty_by_instrument[asset.instrument_id]) \
            if asset.instrument_id in dirty_by_instrument else next_day
        if instrument_start > through:
            continue
        previous = session.scalar(select(PositionSnapshot).where(
            PositionSnapshot.portfolio_id == portfolio_id,
            PositionSnapshot.instrument_id == asset.instrument_id,
            PositionSnapshot.date == instrument_start - timedelta(days=1),
            PositionSnapshot.reporting_currency == CANONICAL_CURRENCY,
        ))
        asset_start = instrument_start if previous else min(row.trade_date for row in rows)
        activity_rows = [row for row in rows if row.trade_date >= asset_start]
        activity_events = [event for event in events if event.effective_date >= asset_start]
        # Intraday/latest quotes are not final daily closes.
        active_prices = [price for price in get_quote_history(session, asset) if price.date <= through]
        factors = reporting_factors(session, CANONICAL_CURRENCY,
                                    activity_rows, activity_events, active_prices)
        # Every carried observation uses valuation-day FX, not quote-day FX.
        currencies = {price.currency for price in active_prices}
        day = asset_start
        while day <= through:
            for currency in currencies:
                key = (currency, day)
                if key not in factors:
                    try:
                        factors[key] = convert_amount(session, Decimal('1'), currency,
                                                      CANONICAL_CURRENCY, day,
                                                      fetcher=lambda *_: [])
                    except RateUnavailable:
                        pass
            day += timedelta(days=1)
        series = position_history(
            activity_rows, activity_events, active_prices, CANONICAL_CURRENCY,
            factors, start=asset_start, end=through,
            initial_state=previous.ledger_state if previous else None,
            missing_action_ranges=action_gaps_by_instrument.get(asset.instrument_id, ()),
            missing_price_ranges=price_gaps_by_instrument.get(asset.instrument_id, ()),
        )
        session.execute(delete(PositionSnapshot).where(
            PositionSnapshot.portfolio_id == portfolio_id,
            PositionSnapshot.instrument_id == asset.instrument_id,
            PositionSnapshot.date >= min(instrument_start, asset_start),
        ))
        for item in series:
            session.add(PositionSnapshot(
                portfolio_id=portfolio_id, instrument_id=asset.instrument_id,
                date=item['date'], reporting_currency=CANONICAL_CURRENCY,
                status=item['status'], ledger_state=item['ledger_state'],
                quote_date=item['quote_date'],
                **{field: item[field] for field in POSITION_FIELDS},
            ))
        if any(item['status'] != 'complete' for item in series):
            history_incomplete.append(asset.instrument.symbol)
            if asset.instrument.symbol not in incomplete:
                incomplete.append(asset.instrument.symbol)
    session.flush()
    if start <= through:
        previous_portfolio = session.scalar(select(PortfolioSnapshot).where(
            PortfolioSnapshot.portfolio_id == portfolio_id,
            PortfolioSnapshot.date == start - timedelta(days=1),
            PortfolioSnapshot.reporting_currency == CANONICAL_CURRENCY,
        ))
        previous_value = previous_portfolio.market_value if previous_portfolio else ZERO
        factor = previous_portfolio.return_factor if previous_portfolio else Decimal('1')
        session.execute(delete(PortfolioSnapshot).where(
            PortfolioSnapshot.portfolio_id == portfolio_id,
            PortfolioSnapshot.date >= start,
        ))
        day = start
        while day <= through:
            daily_rows = list(session.scalars(select(PositionSnapshot).where(
                PositionSnapshot.portfolio_id == portfolio_id,
                PositionSnapshot.date == day,
            )))
            fixed_rows = daily_position_rows(session, all_lots, day,
                                             CANONICAL_CURRENCY)
            daily_rows.extend(fixed_rows)
            values = portfolio_day(daily_rows, previous_value, factor)
            if (fixed_rows and values['status'] == 'complete'
                    and values['cumulative_return_pct'] is None):
                values['status'] = 'incomplete_history'
            session.add(PortfolioSnapshot(
                portfolio_id=portfolio_id, date=day,
                reporting_currency=CANONICAL_CURRENCY,
                **values,
            ))
            previous_value = values['market_value']
            factor = values['return_factor']
            day += timedelta(days=1)
        portfolio.history_built_through = through
    # A suffix replay or a quote-only refresh must retain earlier gaps in the
    # result, even when no snapshot was rebuilt in this request.
    symbols = {asset.instrument_id: asset.instrument.symbol for asset in assets}
    incomplete_rows = session.scalars(select(PositionSnapshot).where(
        PositionSnapshot.portfolio_id == portfolio_id,
        PositionSnapshot.reporting_currency == CANONICAL_CURRENCY,
        PositionSnapshot.status != 'complete',
    ).order_by(PositionSnapshot.date))
    status_reasons = {
        'missing_price': 'fechamento ausente',
        'missing_fx': 'câmbio ausente',
        'missing_price_and_fx': 'fechamento e câmbio ausentes',
        'incomplete_history': 'retorno interrompido por lacuna anterior',
        'missing_actions': 'cobertura de eventos corporativos incompleta',
        'missing_price_history': 'consulta de fechamentos incompleta',
    }
    first_gaps = {}
    for snapshot in incomplete_rows:
        symbol = symbols.get(snapshot.instrument_id)
        if symbol and symbol not in first_gaps:
            first_gaps[symbol] = snapshot
    history_incomplete = sorted(first_gaps)
    for symbol, snapshot in first_gaps.items():
        problems[symbol].append(
            f"{status_reasons.get(snapshot.status, 'dado histórico incompleto')} em {snapshot.date.strftime('%d/%m/%Y')}")
    incomplete = sorted(set(incomplete) | set(history_incomplete))
    # Dirty means source changes have not been replayed. Missing observations
    # are a separate state and should not make every click restart at trade one.
    session.execute(delete(PositionInvalidation).where(
        PositionInvalidation.portfolio_id == portfolio_id,
        PositionInvalidation.instrument_id.in_(selected_ids),
    ))
    portfolio.dirty_from = session.scalar(select(PositionInvalidation.dirty_from).where(
        PositionInvalidation.portfolio_id == portfolio_id).order_by(PositionInvalidation.dirty_from).limit(1))
    session.flush()
    for position in position_valuations(session, all_lots, valuation_date,
                                        CANONICAL_CURRENCY):
        if position['status'] != 'complete':
            problems[position['asset']].append('Fixed-income valuation incomplete')
            incomplete.append(position['asset'])
    historical_gap = session.scalar(select(PortfolioSnapshot.id).where(
            PortfolioSnapshot.portfolio_id == portfolio_id,
            PortfolioSnapshot.status != 'complete').limit(1)) is not None
    if historical_gap:
        history_incomplete.append('portfolio')
        if not incomplete and all_lots:
            for lot in all_lots:
                problems[lot.asset.instrument.symbol].append('Fixed-income history incomplete')
                incomplete.append(lot.asset.instrument.symbol)
    incomplete = sorted(set(incomplete))
    return {
        'complete': not incomplete,
        'history_status': 'complete' if not history_incomplete else 'incomplete',
        'recalculated_from': start if start <= through else None,
        'incomplete_assets': sorted(set(incomplete)),
        'snapshot_days': (through - start).days + 1 if start <= through else 0,
        'reasons': {symbol: list(dict.fromkeys(details)) for symbol, details in problems.items()},
        'message': ('Consolidação parcial: ' + '; '.join(
            symbol + ' (' + ', '.join(dict.fromkeys(problems[symbol])) + ')'
            for symbol in incomplete) + '.'
                    if incomplete else 'Carteira consolidada.'),
    }
