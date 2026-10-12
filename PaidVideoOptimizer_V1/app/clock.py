from datetime import datetime, timezone, timedelta

def business_today():
    """All report cutoff and freshness checks use Asia/Shanghai (UTC+08:00)."""
    return datetime.now(timezone(timedelta(hours=8))).date()
