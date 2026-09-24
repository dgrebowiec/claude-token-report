"""Token types and how much each one counts ("weighted tokens").

One weighted token = one normal (uncached) input token of the reference model (Opus 5).
Anthropic does not publish the formula behind subscription usage limits; relative API prices
are the best public proxy — a pricier model or token type uses the limit faster. Only the
ratios below matter, not the money.
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Set, Tuple

from .i18n import L

W_INPUT, W_CACHE_READ, W_WRITE_5M, W_WRITE_1H, W_OUTPUT = 1.0, 0.1, 1.25, 2.0, 5.0

TOKEN_TYPES = ("input", "cache_read", "cache_write_5m", "cache_write_1h", "output")
TYPE_WEIGHTS = {"input": W_INPUT, "cache_read": W_CACHE_READ, "cache_write_5m": W_WRITE_5M,
                "cache_write_1h": W_WRITE_1H, "output": W_OUTPUT}

Price = Tuple[float, float, float]  # input, output, cache read — per 1M tokens

# Relative API prices: (substring of model id, input, output, cache read).
# Checked in order — more specific names first.
_PRICES: List[Tuple[str, float, float, float]] = [
    ("fable-5-1", 10.0, 50.0, 0.25),
    ("mythos-5-1", 10.0, 50.0, 0.25),
    ("fable-5", 10.0, 50.0, 1.00),
    ("mythos-5", 10.0, 50.0, 1.00),
    ("opus-5-5", 4.0, 20.0, 0.20),
    ("opus-5", 5.0, 25.0, 0.50),
    ("opus-4-8", 5.0, 25.0, 0.50),
    ("opus-4-7", 5.0, 25.0, 0.50),
    ("opus-4-6", 5.0, 25.0, 0.50),
    ("opus-4-5", 5.0, 25.0, 0.50),
    ("opus-4", 15.0, 75.0, 1.50),      # Opus 4 / 4.1
    ("3-opus", 15.0, 75.0, 1.50),
    ("sonnet-5", 2.0, 10.0, 0.20),
    ("sonnet", 3.0, 15.0, 0.30),       # Sonnet 3.7 / 4 / 4.5 / 4.6
    ("haiku-4-5", 1.0, 5.0, 0.10),
    ("3-5-haiku", 0.8, 4.0, 0.08),
    ("3-haiku", 0.25, 1.25, 0.025),
    ("haiku", 1.0, 5.0, 0.10),
]
REF_PRICE = 5.0  # input price of the reference model (Opus 5) -> model weight 1.0
_FALLBACK_PRICE: Price = (5.0, 25.0, 0.50)  # unknown models are counted as Opus 5
_unknown_models: Set[str] = set()


def price_for(model: str) -> Price:
    ml = (model or "").lower()
    for pattern, p_in, p_out, p_cache_read in _PRICES:
        if pattern in ml:
            return p_in, p_out, p_cache_read
    _unknown_models.add(model or "?")
    return _FALLBACK_PRICE


def model_weight(model: str) -> float:
    return price_for(model)[0] / REF_PRICE


def unknown_models() -> List[str]:
    """models seen so far that are not in the price table (weighted as Opus 5)"""
    return sorted(_unknown_models)


def type_name(token_type: str) -> str:
    return {
        "input": L("wejście (nowy tekst)", "input (new text)"),
        "cache_read": L("odczyt z cache", "cache read"),
        "cache_write_5m": L("zapis do cache 5 min", "cache write 5 min"),
        "cache_write_1h": L("zapis do cache 1 h", "cache write 1 h"),
        "output": L("wyjście (odpowiedź)", "output (response)"),
    }[token_type]


def split_usage(usage: Mapping) -> Dict[str, int]:
    """the API "usage" record -> token count per TOKEN_TYPES entry"""
    cache_creation = usage.get("cache_creation") or {}
    write_5m = cache_creation.get("ephemeral_5m_input_tokens", 0) or 0
    write_1h = cache_creation.get("ephemeral_1h_input_tokens", 0) or 0
    if not write_5m and not write_1h:
        write_5m = usage.get("cache_creation_input_tokens", 0) or 0  # older records: no split
    return {"input": usage.get("input_tokens", 0) or 0,
            "cache_read": usage.get("cache_read_input_tokens", 0) or 0,
            "cache_write_5m": write_5m, "cache_write_1h": write_1h,
            "output": usage.get("output_tokens", 0) or 0}


def context_size(tokens: Mapping[str, float]) -> float:
    """everything the model read in a call: the whole conversation so far"""
    return (tokens["input"] + tokens["cache_read"]
            + tokens["cache_write_5m"] + tokens["cache_write_1h"])


def weighted_by_type(tokens: Mapping[str, int], model: str) -> Dict[str, float]:
    """weighted tokens per token type: token type weight × model weight"""
    p_in, p_out, p_cache_read = price_for(model)
    return {"input": tokens["input"] * p_in / REF_PRICE,
            "cache_read": tokens["cache_read"] * p_cache_read / REF_PRICE,
            "cache_write_5m": tokens["cache_write_5m"] * p_in * W_WRITE_5M / REF_PRICE,
            "cache_write_1h": tokens["cache_write_1h"] * p_in * W_WRITE_1H / REF_PRICE,
            "output": tokens["output"] * p_out / REF_PRICE}


def cache_rewrite_waste(tokens: Mapping[str, int], model: str) -> float:
    """how much more a cache write weighed than reading the same tokens from the cache"""
    p_in, _p_out, p_cache_read = price_for(model)
    return (tokens["cache_write_5m"] * (p_in * W_WRITE_5M - p_cache_read)
            + tokens["cache_write_1h"] * (p_in * W_WRITE_1H - p_cache_read)) / REF_PRICE
