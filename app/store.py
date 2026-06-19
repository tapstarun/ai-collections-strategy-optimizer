"""Loads the synthetic borrower dataset and provides lookup helpers.

In a real system this would be a database access layer with row-level security;
here it is an in-memory dict loaded from JSON. Access-control is enforced one
layer up (auth.py), not here, so this module stays a pure data store.
"""
from __future__ import annotations

import json
from functools import lru_cache

from .config import DATA_FILE
from .models import Borrower


@lru_cache(maxsize=1)
def _load() -> dict[str, Borrower]:
    with open(DATA_FILE, encoding="utf-8") as fh:
        raw = json.load(fh)
    borrowers = [Borrower.model_validate(item) for item in raw]
    return {b.borrower_id: b for b in borrowers}


def all_borrowers() -> list[Borrower]:
    return list(_load().values())


def get_borrower(borrower_id: str) -> Borrower | None:
    return _load().get(borrower_id)
