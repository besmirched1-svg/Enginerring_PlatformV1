import json
import logging
import requests
from typing import Optional

logger = logging.getLogger("engine.notifier")

# Fallback channel to accept external webhook targets safely
GLOBAL_WEBHOOK_URL: Optional[str] = None

def dispatch_cluster_alert(title: str, text: str, alert_level: str = "INFO") -> bool:
    """
    Outbound Gateway Messenger: Converts internal telemetry alerts into unified
    structured payloads and posts them directly over external HTTP webhook channels.
    """
    if not GLOBAL_WEBHOOK_URL:
        logger.info(f"[MOCK NOTIFIER - {alert_level}] {title}: {text}")
        return True
        
    emoji = "ℹ️"
    if alert_level == "WARNING": emoji = "⚠️"
    elif alert_level == "CRITICAL": emoji = "🚨"
    elif alert_level == "SUCCESS": emoji = "🏆"
    
    payload = {
        "username": "OpenSCAD Engineering Platform Bot",
        "text": f"{emoji} *{title}*\n{text}",
        "attachments": [{
            "color": "#ff9f1c" if alert_level == "WARNING" else "#2ec4b6",
            "fields": [
                {"title": "Status Matrix Level", "value": alert_level, "short": True}
            ]
        }]
    }
    
    try:
        res = requests.post(GLOBAL_WEBHOOK_URL, json=payload, headers={"Content-Type": "application/json"}, timeout=5.0)
        if res.status_code in [200, 201, 204]:
            logger.info("Outbound cluster notification dispatched successfully.")
            return True
        logger.warning(f"External communications endpoint rejected payload context: {res.status_code}")
        return False
    except Exception as e:
        logger.error(f"Network barrier obstructing external notification tunnel: {str(e)}")
        return False
