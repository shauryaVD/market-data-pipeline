from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

import pandas as pd

from market_data_pipeline.config import SourceConfig, TradingCalendar

CANONICAL_COLUMNS = [
    "source_name",
    "symbol",
    "price_ts",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "adjusted_close",
    "currency",
]


@dataclass(frozen=True)
class TransformationResult:
    valid_rows: pd.DataFrame
    rejected_rows: pd.DataFrame
    rows_read: int
    duplicates_dropped: int

    @property
    def rows_valid(self) -> int:
        return len(self.valid_rows)

    @property
    def rows_rejected(self) -> int:
        return len(self.rejected_rows)


def read_market_csv(source: SourceConfig) -> pd.DataFrame:
    return pd.read_csv(source.path)


def transform_market_data(
    raw: pd.DataFrame,
    source: SourceConfig,
    now: datetime | None = None,
) -> TransformationResult:
    now = now or datetime.now(UTC)
    rows_read = len(raw)
    renamed = _rename_columns(raw, source)
    working = _ensure_optional_columns(renamed.copy())
    reasons: list[list[str]] = [[] for _ in range(len(working))]

    _validate_required_fields(working, source, reasons)
    _normalize_symbols_and_currency(working, reasons)
    _parse_timestamps(working, source, now, reasons)
    _parse_numeric_fields(working, reasons)
    _validate_business_rules(working, source, now, reasons)
    _validate_trading_calendar(working, source.trading_calendar, reasons)

    reason_text = ["; ".join(row_reasons) for row_reasons in reasons]
    invalid_mask = pd.Series([bool(row_reasons) for row_reasons in reasons], index=working.index)

    rejected = raw.loc[invalid_mask].copy()
    if not rejected.empty:
        rejected["rejection_reason"] = pd.Series(reason_text, index=working.index).loc[invalid_mask]

    valid = working.loc[~invalid_mask].copy()
    valid["source_name"] = source.name
    valid = valid[CANONICAL_COLUMNS]
    valid = valid.sort_values(["source_name", "symbol", "price_ts"], kind="stable")
    before_dedupe = len(valid)
    valid = valid.drop_duplicates(
        subset=["source_name", "symbol", "price_ts"],
        keep="last",
    ).reset_index(drop=True)
    duplicates_dropped = before_dedupe - len(valid)

    return TransformationResult(
        valid_rows=valid,
        rejected_rows=rejected.reset_index(drop=True),
        rows_read=rows_read,
        duplicates_dropped=int(duplicates_dropped),
    )


def _rename_columns(raw: pd.DataFrame, source: SourceConfig) -> pd.DataFrame:
    reverse_mapping = {csv_column: canonical for canonical, csv_column in source.columns.items()}
    missing = sorted(set(source.columns.values()) - set(raw.columns))
    if missing:
        raise ValueError(f"CSV missing configured columns: {', '.join(missing)}")

    renamed = raw.rename(columns=reverse_mapping)
    return renamed[list(reverse_mapping.values())]


def _ensure_optional_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if "adjusted_close" not in frame.columns:
        frame["adjusted_close"] = pd.NA
    return frame


def _validate_required_fields(
    frame: pd.DataFrame,
    source: SourceConfig,
    reasons: list[list[str]],
) -> None:
    for column in source.required_columns:
        if column not in frame.columns:
            for row_reasons in reasons:
                row_reasons.append(f"missing_column:{column}")
            continue

        missing_mask = frame[column].isna() | (frame[column].astype(str).str.strip() == "")
        for index in frame.index[missing_mask]:
            reasons[int(index)].append(f"missing_required:{column}")


def _normalize_symbols_and_currency(frame: pd.DataFrame, reasons: list[list[str]]) -> None:
    frame["symbol"] = frame["symbol"].astype("string").str.strip().str.upper()
    frame["currency"] = frame["currency"].astype("string").str.strip().str.upper()

    invalid_symbol = frame["symbol"].isna() | (frame["symbol"].str.len() == 0)
    invalid_currency = frame["currency"].isna() | ~frame["currency"].str.fullmatch(r"[A-Z]{3}")

    for index in frame.index[invalid_symbol]:
        reasons[int(index)].append("invalid_symbol")
    for index in frame.index[invalid_currency]:
        reasons[int(index)].append("invalid_currency")


def _parse_timestamps(
    frame: pd.DataFrame,
    source: SourceConfig,
    now: datetime,
    reasons: list[list[str]],
) -> None:
    parsed = pd.to_datetime(frame["timestamp"], errors="coerce", format="mixed")

    if parsed.dt.tz is None:
        source_ts = parsed.dt.tz_localize(
            source.timezone.source,
            ambiguous="NaT",
            nonexistent="shift_forward",
        )
    else:
        source_ts = parsed.dt.tz_convert(source.timezone.source)

    frame["_source_ts"] = source_ts
    frame["price_ts"] = source_ts.dt.tz_convert(source.timezone.target)

    invalid_ts = frame["price_ts"].isna()
    for index in frame.index[invalid_ts]:
        reasons[int(index)].append("invalid_timestamp")

    if not source.business_rules.allow_future_timestamps:
        target_now = pd.Timestamp(now).tz_convert(source.timezone.target)
        future_cutoff = target_now + pd.Timedelta(timedelta(minutes=5))
        future_mask = frame["price_ts"].notna() & (frame["price_ts"] > future_cutoff)
        for index in frame.index[future_mask]:
            reasons[int(index)].append("future_timestamp")


def _parse_numeric_fields(frame: pd.DataFrame, reasons: list[list[str]]) -> None:
    for source_column, target_column in {
        "open": "open_price",
        "high": "high_price",
        "low": "low_price",
        "close": "close_price",
        "adjusted_close": "adjusted_close",
    }.items():
        frame[target_column] = frame[source_column].apply(_parse_decimal)

    for column in ["open_price", "high_price", "low_price", "close_price", "volume"]:
        if column == "volume":
            continue
        invalid_mask = frame[column].isna()
        for index in frame.index[invalid_mask]:
            reasons[int(index)].append(f"invalid_number:{column}")

    frame["volume"] = frame["volume"].apply(_parse_int)
    invalid_volume = frame["volume"].isna()
    for index in frame.index[invalid_volume]:
        reasons[int(index)].append("invalid_integer:volume")


def _validate_business_rules(
    frame: pd.DataFrame,
    source: SourceConfig,
    now: datetime,
    reasons: list[list[str]],
) -> None:
    del now
    rules = source.business_rules

    if rules.require_positive_prices:
        for column in ["open_price", "high_price", "low_price", "close_price", "adjusted_close"]:
            invalid_mask = frame[column].notna() & (frame[column] <= 0)
            for index in frame.index[invalid_mask]:
                reasons[int(index)].append(f"non_positive_price:{column}")

    if rules.require_non_negative_volume:
        invalid_volume = frame["volume"].notna() & (frame["volume"] < 0)
        for index in frame.index[invalid_volume]:
            reasons[int(index)].append("negative_volume")

    if rules.require_high_low_envelope:
        for index, row in frame.iterrows():
            values = [row["open_price"], row["high_price"], row["low_price"], row["close_price"]]
            if any(value is None or pd.isna(value) for value in values):
                continue
            open_price, high_price, low_price, close_price = values
            if high_price < max(open_price, low_price, close_price) or low_price > min(
                open_price, high_price, close_price
            ):
                reasons[int(index)].append("invalid_high_low_envelope")


def _validate_trading_calendar(
    frame: pd.DataFrame,
    calendar: TradingCalendar,
    reasons: list[list[str]],
) -> None:
    if not calendar.enabled:
        return

    for index, source_ts in frame["_source_ts"].items():
        if pd.isna(source_ts):
            continue
        local_date = source_ts.date().isoformat()
        local_time = source_ts.time()
        if source_ts.weekday() >= 5:
            reasons[int(index)].append("market_closed_weekend")
        if local_date in calendar.holidays:
            reasons[int(index)].append("market_closed_holiday")
        if local_time < calendar.market_open or local_time > calendar.market_close:
            reasons[int(index)].append("outside_market_hours")


def _parse_decimal(value) -> Decimal | None:
    if pd.isna(value) or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value).strip())
    except InvalidOperation:
        return None


def _parse_int(value) -> int | None:
    if pd.isna(value) or str(value).strip() == "":
        return None
    try:
        decimal_value = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    if decimal_value != decimal_value.to_integral_value():
        return None
    return int(decimal_value)
