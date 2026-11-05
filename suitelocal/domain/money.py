DECIMAL_SEPARATORS = (",", ".")


def format_usd(cents: int, decimal_separator: str = ",") -> str:
    """Format integer cents as USD: "$ 1.234,56" (comma) or "$ 1,234.56" (dot)."""
    if decimal_separator not in DECIMAL_SEPARATORS:
        raise ValueError("El separador decimal debe ser «,» o «.».")
    group_separator = "." if decimal_separator == "," else ","
    units, remainder = divmod(abs(cents), 100)
    grouped = f"{units:,}".replace(",", group_separator)
    sign = "-" if cents < 0 else ""
    return f"{sign}$ {grouped}{decimal_separator}{remainder:02d}"
