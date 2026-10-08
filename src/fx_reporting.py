"""Read-only FX requirements and stored history for one authorized portfolio."""
from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta, timezone

from sqlalchemy import select

from src.config import rate_fallback_days
from src.corporate_actions import get_stored_actions
from src.domain import corporate_event_effects
from src.fixed_income import list_lots
from src.market_prices import accounting_currency, get_quote_history, valuation_currency
from src.models import ExchangeRate, FixedIncomeSnapshot, PositionInvalidation, PositionSnapshot
from src.position_reporting import sources


def portfolio_fx_coverage(session, portfolio_id):
    portfolio, transactions, assets = sources(session, portfolio_id)
    today = date.today()
    required = defaultdict(lambda: defaultdict(set))

    def need(source, target, day, reason):
        if source == target or day > today:
            return
        for currency in {source, target} - {'BRL', None}:
            required[currency][day].add(reason)

    snapshots = list(session.scalars(select(PositionSnapshot).where(
        PositionSnapshot.portfolio_id == portfolio_id, PositionSnapshot.date <= today).order_by(PositionSnapshot.date)))
    dirty = dict(session.execute(select(PositionInvalidation.instrument_id, PositionInvalidation.dirty_from).where(
        PositionInvalidation.portfolio_id == portfolio_id)).all())
    by_instrument = defaultdict(dict)
    for row in snapshots:
        by_instrument[row.instrument_id][row.date] = row
    pending_requirements = False
    unknown_requirements = []
    for asset in assets:
        if asset.instrument.asset_type == 'FIXED_INCOME':
            continue
        trades = [row for row in transactions if row.instrument_id == asset.instrument_id]
        saved = by_instrument[asset.instrument_id]
        if not trades and not saved:
            continue
        try:
            accounting = accounting_currency(session, asset)
        except ValueError:
            unknown_requirements.append(asset.instrument.symbol)
            continue
        targets = {accounting, portfolio.display_currency}
        for trade in trades:
            for target in targets:
                if trade.transaction_currency == target:
                    continue
                # Reporting uses the frozen transaction BRL rate, not today's source rate.
                if target == 'BRL' and trade.fx_rate is not None:
                    continue
                need('BRL', target, trade.settlement_date, 'transaction_reporting')
        events = get_stored_actions(session, asset, end=today)
        for effect in corporate_event_effects(trades, events):
            event = effect['event']
            if effect['gross_amount'] is not None and effect['eligible_quantity'] > 0:
                for target in targets:
                    need(event.currency, target, event.effective_date, 'income_reporting')
        quotes = get_quote_history(session, asset)
        quote_days = [row.date for row in quotes]
        first = min([row.trade_date for row in trades] + list(saved))
        last_saved = saved[max(saved)] if saved else None
        for offset in range(max(0, (today - first).days + 1)):
            day = first + timedelta(days=offset)
            snapshot = saved.get(day) or (last_saved if last_saved and day > last_saved.date else None)
            if asset.instrument_id in dirty and day >= dirty[asset.instrument_id]:
                snapshot = None
            if snapshot is not None and snapshot.quantity == 0:
                continue
            # Unbuilt holdings cannot certify exact requirements; show this explicitly.
            if snapshot is None:
                pending_requirements = True
            index = bisect_right(quote_days, day) - 1
            currency = quotes[index].currency if index >= 0 else valuation_currency(session, asset)
            for target in targets:
                need(currency, target, day, 'valuation')

    fixed = list(session.scalars(select(FixedIncomeSnapshot).where(
        FixedIncomeSnapshot.portfolio_id == portfolio_id,
        FixedIncomeSnapshot.date <= today).order_by(FixedIncomeSnapshot.date)))
    latest_lots = {}
    for row in fixed:
        need(row.accounting_currency, portfolio.display_currency, row.date, 'fixed_income_valuation')
        latest_lots[row.lot_id] = row
    for row in latest_lots.values():
        if row.instrument_id in dirty or row.date < today:
            pending_requirements = True
        for offset in range(1, max(0, (today - row.date).days) + 1):
            need(row.accounting_currency, portfolio.display_currency, row.date + timedelta(days=offset),
                 'fixed_income_valuation')
    for lot in list_lots(session, portfolio_id):
        if lot.start_date <= today and (lot.id not in latest_lots or lot.asset.instrument_id in dirty):
            pending_requirements = True
            # Retain saved-history requirements while adding the edited source
            # range. Backdated applications can precede every saved snapshot.
            for offset in range(max(0, (today - lot.start_date).days + 1)):
                need(lot.currency, portfolio.display_currency, lot.start_date + timedelta(days=offset),
                     'fixed_income_valuation')

    fallback = rate_fallback_days()
    first_required = min((day for days in required.values() for day in days), default=today)
    stored = list(session.scalars(select(ExchangeRate).where(
        ExchangeRate.currency.in_(required),
        ExchangeRate.reference_date >= first_required - timedelta(days=fallback),
        ExchangeRate.reference_date <= today,
    ).order_by(ExchangeRate.currency, ExchangeRate.reference_date, ExchangeRate.rate_type,
               ExchangeRate.rate_side))) if required else []
    pairs = []
    for currency, days in sorted(required.items()):
        history = [row for row in stored if row.currency == currency]
        market = [row for row in history if row.rate_type == 'FX' and row.rate_side == 'MARKET']
        references = [row.reference_date for row in market]
        requirements = []
        for day, reasons in sorted(days.items()):
            index = bisect_right(references, day) - 1
            reference = references[index] if index >= 0 and (day - references[index]).days <= fallback else None
            requirements.append({'date': day, 'reasons': sorted(reasons), 'reference_date': reference,
                                 'fallback_used': reference is not None and reference != day})
        missing = [row['date'] for row in requirements if row['reference_date'] is None]
        retrieved = [row.retrieved_at.replace(tzinfo=timezone.utc) if row.retrieved_at.tzinfo is None
                     else row.retrieved_at for row in history if row.retrieved_at is not None]
        pairs.append({'currency': currency, 'base_currency': 'BRL', 'required_rate_type': 'FX',
            'required_start': min(days), 'required_end': max(days),
            'required_count': len(days), 'covered_count': len(days) - len(missing),
            'missing_dates': missing, 'requirements': requirements,
            'status': 'incomplete' if missing else 'complete',
            'available_start': min(references, default=None), 'available_end': max(references, default=None),
            'sources': sorted({row.source for row in history}),
            'last_observation_retrieved_at': max(retrieved, default=None),
            'history': [{'reference_date': row.reference_date, 'rate_type': row.rate_type,
                         'side': row.rate_side, 'rate': row.rate, 'source': row.source,
                         'retrieved_at': row.retrieved_at} for row in history]})
    return {'portfolio_id': portfolio_id, 'reporting_currency': portfolio.display_currency,
            'as_of': today, 'fallback_days': fallback, 'pairs': pairs,
            'status': 'incomplete' if unknown_requirements or any(pair['missing_dates'] for pair in pairs)
                      else 'pending' if pending_requirements and pairs else 'complete',
            'requirements_status': 'incomplete' if unknown_requirements else 'pending' if pending_requirements else 'complete',
            'unknown_requirements': unknown_requirements,
            'last_successful_sync_at': None, 'sync_tracking': 'not_recorded'}
