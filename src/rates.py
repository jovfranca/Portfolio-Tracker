"""Local-first retrieval and insert-only storage for historical rates."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.api import market_data
from src.config import rate_fallback_days
from src.models import ExchangeRate


class RateUnavailable(ValueError):
    pass


def _normalize(currency, rate_type):
    currency = currency.strip().upper()
    rate_type = rate_type.strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError('Moeda deve usar um código alfabético ISO de três letras.')
    if rate_type not in {'FX', 'PTAX'}:
        raise ValueError('Tipo de cotação deve ser FX ou PTAX.')
    return currency, rate_type


def _find_on_date(session, currency, rate_type, reference_date):
    return list(session.scalars(select(ExchangeRate).where(
        ExchangeRate.currency == currency,
        ExchangeRate.rate_type == rate_type,
        ExchangeRate.reference_date == reference_date,
    ).order_by(ExchangeRate.rate_side)))


def _is_complete(rates, rate_type):
    sides = {rate.rate_side for rate in rates}
    return sides >= ({'BUY', 'SELL'} if rate_type == 'PTAX' else {'MARKET'})


def _find_previous(session, currency, rate_type, reference_date, fallback_days):
    rows = list(session.scalars(
        select(ExchangeRate)
        .where(
            ExchangeRate.currency == currency,
            ExchangeRate.rate_type == rate_type,
            ExchangeRate.reference_date < reference_date,
            ExchangeRate.reference_date >= reference_date - timedelta(days=fallback_days),
        )
        .order_by(ExchangeRate.reference_date.desc(), ExchangeRate.rate_side)
    ))
    for candidate_date in dict.fromkeys(row.reference_date for row in rows):
        candidates = [row for row in rows if row.reference_date == candidate_date]
        if _is_complete(candidates, rate_type):
            return candidates
    return []


def store_rates(session, rows):
    """Insert unseen historical values; never update an existing rate."""
    inserted = 0
    # Roll back the whole provider batch if any observation cannot be stored.
    with session.begin_nested():
        for row in sorted(rows, key=lambda item: (item['reference_date'], item['rate_side'])):
            currency, rate_type = _normalize(row['currency'], row['rate_type'])
            rate_side = row['rate_side'].strip().upper()
            allowed_sides = {'BUY', 'SELL'} if rate_type == 'PTAX' else {'MARKET'}
            if rate_side not in allowed_sides:
                raise ValueError(f'Lado {rate_side!r} inválido para {rate_type}.')
            existing = select(ExchangeRate).where(
                ExchangeRate.currency == currency,
                ExchangeRate.rate_type == rate_type,
                ExchangeRate.reference_date == row['reference_date'],
                ExchangeRate.rate_side == rate_side,
            )
            if session.scalar(existing) is not None:
                continue
            try:
                with session.begin_nested():
                    session.add(ExchangeRate(
                        currency=currency,
                        rate_type=rate_type,
                        rate_side=rate_side,
                        reference_date=row['reference_date'],
                        rate=row['rate'],
                        source=row['source'],
                        retrieved_at=row['retrieved_at'],
                    ))
                    session.flush()
            except IntegrityError:
                # Another request may have stored this key after our lookup.
                # Only suppress that conflict, never other constraint failures.
                if session.scalar(existing) is None:
                    raise
            else:
                inserted += 1
    return inserted


def get_rates(session, currency, rate_type, reference_date, fetcher=None):
    """Return complete cached observations without choosing an applicable side.

    Weekends reuse a cached Friday immediately. For other missing
    dates the provider is queried for the fallback window, after which the most
    recent earlier published rate is used (covering holidays).
    """
    currency, rate_type = _normalize(currency, rate_type)
    if reference_date > date.today():
        raise ValueError('A data de referência não pode estar no futuro.')
    fallback_days = rate_fallback_days()
    exact = _find_on_date(session, currency, rate_type, reference_date)
    if _is_complete(exact, rate_type):
        return exact

    previous = _find_previous(session, currency, rate_type, reference_date, fallback_days)
    if reference_date.weekday() >= 5 and previous:
        friday = reference_date - timedelta(days=reference_date.weekday() - 4)
        if previous[0].reference_date == friday:
            return previous

    fetcher = fetcher or market_data.fetch_rates
    try:
        rows = fetcher(
            currency,
            rate_type,
            reference_date - timedelta(days=fallback_days),
            reference_date,
        )
    except Exception as error:
        if previous:
            return previous
        raise RateUnavailable(
            f'Não há taxa {rate_type} de {currency} disponível para {reference_date}.'
        ) from error

    store_rates(session, rows)
    resolved = _find_on_date(session, currency, rate_type, reference_date)
    if not _is_complete(resolved, rate_type):
        resolved = _find_previous(session, currency, rate_type, reference_date, fallback_days)
    if not resolved:
        raise RateUnavailable(
            f'Não há taxa {rate_type} de {currency} disponível para {reference_date}.'
        )
    return resolved


def backfill_rates(session, currencies, rate_types, start, end, fetcher=None):
    """Fetch each currency/type range once and insert only missing provider dates."""
    if end < start:
        raise ValueError('A data final deve ser igual ou posterior à data inicial.')
    if end > date.today():
        raise ValueError('A data final não pode estar no futuro.')
    fetcher = fetcher or market_data.fetch_rates
    inserted = 0
    requested = []
    for currency in currencies:
        for rate_type in rate_types:
            normalized = _normalize(currency, rate_type)
            if normalized in requested:
                continue
            requested.append(normalized)
            inserted += store_rates(session, fetcher(*normalized, start, end))
    return {'inserted': inserted, 'series': len(requested)}
