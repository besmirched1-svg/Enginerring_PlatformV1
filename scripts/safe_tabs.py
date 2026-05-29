#!/usr/bin/env python3
# scripts/safe_tabs.py
# Safe sanitizer for Edge tab metadata. This script does NOT embed raw metadata.
# If you have raw metadata, save it as dev_data/edge_tabs_raw.json and this script will load and sanitize it.

import json
import re
from typing import Dict, List, Optional
import os

_RAW_PATH = os.path.join("dev_data", "edge_tabs_raw.json")
_SANITIZED_PATH = os.path.join("dev_data", "edge_tabs_sanitized.json")

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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)

def load_raw_if_exists(path: str) -> Optional[List[Dict]]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)

def main():
    raw = load_raw_if_exists(_RAW_PATH)
    if raw is None:
        print("No raw metadata found at dev_data/edge_tabs_raw.json. Exiting.")
        return
    sanitized = summarize_tabs(raw)
    save_sanitized_json(_SANITIZED_PATH, sanitized)
    print(f"Sanitized JSON saved to {_SANITIZED_PATH}")

if __name__ == "__main__":
    main()

