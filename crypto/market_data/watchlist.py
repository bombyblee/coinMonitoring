from __future__ import annotations


class Watchlist:
    """In-memory watchlist of Futures symbols. Thread-safe via GIL (list ops)."""

    def __init__(self, symbols: list[str] | None = None):
        self._symbols: list[str] = [s.upper() for s in (symbols or [])]

    def add(self, symbol: str) -> bool:
        """Add symbol. Returns True if newly added, False if already present."""
        s = symbol.upper()
        if s in self._symbols:
            return False
        self._symbols.append(s)
        return True

    def remove(self, symbol: str) -> bool:
        """Remove symbol. Returns True if removed, False if not found."""
        s = symbol.upper()
        try:
            self._symbols.remove(s)
            return True
        except ValueError:
            return False

    def symbols(self) -> list[str]:
        return list(self._symbols)

    def __contains__(self, symbol: str) -> bool:
        return symbol.upper() in self._symbols

    def __len__(self) -> int:
        return len(self._symbols)

    def __repr__(self) -> str:
        return f"Watchlist({self._symbols})"
