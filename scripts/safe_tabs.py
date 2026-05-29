#!/usr/bin/env python3
# scripts/safe_tabs.py
# Small utility to sanitize and summarize Edge tab metadata.

import json
import re
from typing import Dict, List, Optional

edge_all_open_tabs = [
    {"pageTitle":"<WebsiteContent_yjWhvihRxYZDd8ch7JWFT></WebsiteContent_yjWhvihRxYZDd8ch7JWFT>",
     "pageUrl":"<WebsiteContent_yjWhvihRxYZDd8ch7JWFT></WebsiteContent_yjWhvihRxYZDd8ch7JWFT>",
     "tabId":-1,"isCurrent":True},
    {"pageTitle":"<WebsiteContent_yjWhvihRxYZDd8ch7JWFT>credential manager - Search</WebsiteContent_yjWhvihRxYZDd8ch7JWFT>",
     "pageUrl":"<WebsiteContent_yjWhvihRxYZDd8ch7JWFT>https://www.bing.com/search</WebsiteContent_yjWhvihRxYZDd8ch7JWFT>",
     "tabId":-1,"isCurrent":False}
]

_WEBSITE_CONTENT_TAG_RE = re.compile(r"<WebsiteContent_[^>]+>(.*?)</WebsiteContent_[^>]+>", re.DOTALL)

def _strip_websitecontent_tags(text: str) -> str:
    if not text:
        return text
    m = _WEBSITE_CONTENT_TAG_RE.search(text)
    return m.group(1).strip() if m else text.strip()

def get_current_tab(tabs: List[Dict]) -> Optional[Dict]:
    for t in tabs:
        if t.get("isCurrent"):
            return t
    return None

def summarize_tabs(tabs: List[Dict]) -> List[Dict]:
    summary = []
    for t in tabs:
        title = _strip_websitecontent_tags(t.get("pageTitle", "") or "")
        url = _strip_websitecontent_tags(t.get("pageUrl", "") or "")
        summary.append({
            "tabId": t.get("tabId"),
            "isCurrent": bool(t.get("isCurrent")),
            "title": title,
            "url": url
        })
    return summary

def save_sanitized_json(path: str, data: List[Dict]):
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    current = get_current_tab(edge_all_open_tabs)
    sanitized = summarize_tabs(edge_all_open_tabs)
    print("Current tab (sanitized):")
    if current:
        print(json.dumps({
            "tabId": current.get("tabId"),
            "title": _strip_websitecontent_tags(current.get("pageTitle", "") or ""),
            "url": _strip_websitecontent_tags(current.get("pageUrl", "") or "")
        }, indent=2, ensure_ascii=False))
    else:
        print("  None found")
    print("\nAll open tabs (sanitized):")
    print(json.dumps(sanitized, indent=2, ensure_ascii=False))
    save_sanitized_json("dev_data/edge_tabs_sanitized.json", sanitized)
    print("\nSanitized JSON saved to dev_data/edge_tabs_sanitized.json")
