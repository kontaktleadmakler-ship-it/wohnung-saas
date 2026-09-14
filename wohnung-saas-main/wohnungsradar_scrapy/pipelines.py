from __future__ import annotations
from .parsing import parse_number, parse_rents, parse_rooms, parse_size

class NormalizePipeline:
    def process_item(self,item,spider):
        text=" ".join(str(item.get(k) or "") for k in ("title","description","address"))
        if item.get("price") is None or item.get("price_total") is None:
            cold,warm=parse_rents(text)
            if item.get("price") is None: item["price"]=cold
            if item.get("price_total") is None: item["price_total"]=warm
        if item.get("rooms") is not None: item["rooms"]=parse_number(item["rooms"])
        if item.get("size") is not None: item["size"]=parse_number(item["size"])
        if item.get("rooms") is None: item["rooms"]=parse_rooms(text)
        if item.get("size") is None: item["size"]=parse_size(text)
        return item
