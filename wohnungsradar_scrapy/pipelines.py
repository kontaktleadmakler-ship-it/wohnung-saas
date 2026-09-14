from __future__ import annotations

import re


def parse_number(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Keep the common German forms: 1.250,50 -> 1250.50; 65,5 -> 65.5
    cleaned = re.sub(r"[^0-9,.-]", "", text)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


class NormalizePipeline:
    def process_item(self, item, spider):
        # Spider-specific parsers may already provide numeric values. The
        # pipeline is deliberately the single normalization point so every
        # future portal follows the same contract.
        for key in ("price", "price_total", "rooms", "size"):
            if key in item and item[key] is not None and not isinstance(item[key], (int, float)):
                item[key] = parse_number(item[key])
        return item
