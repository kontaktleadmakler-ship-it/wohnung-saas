from __future__ import annotations

import json
from pathlib import Path

from .parsing import parse_number, parse_rents, parse_rooms, parse_size


class NormalizePipeline:
    def process_item(self, item, spider):
        text = " ".join(str(item.get(k) or "") for k in ("title", "description", "address"))
        if item.get("price") is None or item.get("price_total") is None:
            cold, warm = parse_rents(text)
            if item.get("price") is None:
                item["price"] = cold
            if item.get("price_total") is None:
                item["price_total"] = warm
        if item.get("rooms") is not None:
            item["rooms"] = parse_number(item["rooms"])
        if item.get("size") is not None:
            item["size"] = parse_number(item["size"])
        if item.get("rooms") is None:
            item["rooms"] = parse_rooms(text)
        if item.get("size") is None:
            item["size"] = parse_size(text)
        return item


class JobFeedPipeline:
    """One JSONL feed per spider/job; never shares a file between crawlers."""

    def __init__(self):
        self._handles = {}

    def open_spider(self, spider):
        feed_path = getattr(spider, "feed_path", None)
        if not feed_path:
            raise RuntimeError(f"feed_path fehlt für Job {getattr(spider, 'job_id', spider.name)}")
        path = Path(feed_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("w", encoding="utf-8")
        self._handles[id(spider)] = handle
        spider.logger.info("[SCAN-DEBUG][%s] FEED_OPEN path=%s", spider.source_key, path)

    def close_spider(self, spider):
        handle = self._handles.pop(id(spider), None)
        if handle:
            handle.flush()
            handle.close()
            spider.logger.info("[SCAN-DEBUG][%s] FEED_CLOSED", spider.source_key)

    def process_item(self, item, spider):
        handle = self._handles.get(id(spider))
        if handle is None:
            raise RuntimeError(f"Feed handle fehlt für Job {getattr(spider, 'job_id', spider.name)}")
        handle.write(json.dumps(dict(item), ensure_ascii=False, default=str) + "\n")
        handle.flush()
        return item
