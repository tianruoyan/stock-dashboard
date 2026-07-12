from __future__ import annotations

import re
import subprocess
import urllib.request
from datetime import date
from typing import Any, Callable


SINA_API = "https://hq.sinajs.cn/list=si932000"
SINA_PAGE = "https://quotes.sina.cn/hs/company/quotes/view/si932000"


def fetch_quote(timeout: int = 20) -> str:
    request = urllib.request.Request(
        SINA_API,
        headers={"User-Agent": "Mozilla/5.0 V2Research/1.0", "Referer": "https://finance.sina.com.cn/"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except Exception as first_error:
        proc = subprocess.run(
            ["curl", "-L", "--fail", "--silent", "--show-error", "--max-time", str(timeout), "-H", "Referer: https://finance.sina.com.cn/", SINA_API],
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"sina_quote_failed:{type(first_error).__name__}:{proc.stderr.decode(errors='ignore')[:160]}") from first_error
        raw = proc.stdout
    return raw.decode("gb18030", errors="replace")


class V2MicrocapCollector:
    def __init__(self, *, fetcher: Callable[[], str] = fetch_quote) -> None:
        self.fetcher = fetcher

    def collect(self, expected_trade_date: date) -> dict[str, Any]:
        raw = self.fetcher()
        matched = re.search(r'var hq_str_si932000="([^"]*)"', raw)
        if not matched or not matched.group(1):
            raise ValueError("sina_quote_empty")
        fields = matched.group(1).split(",")
        if len(fields) < 33:
            raise ValueError("sina_quote_fields_incomplete")
        name = fields[0]
        previous_close = float(fields[2])
        close = float(fields[3])
        quote_date = date.fromisoformat(fields[30])
        quote_time = fields[31]
        if name != "中证2000":
            raise ValueError("sina_quote_name_mismatch")
        if quote_date != expected_trade_date:
            raise ValueError("sina_quote_trade_date_mismatch")
        if previous_close <= 0 or close <= 0:
            raise ValueError("sina_quote_nonpositive")
        return {
            "observations": [
                {
                    "source_id": "sina_csi2000_secondary_proxy",
                    "trade_date": quote_date.isoformat(),
                    "as_of": f"{quote_date.isoformat()}T{quote_time}+08:00",
                    "close": close,
                    "change_pct": round((close / previous_close - 1) * 100, 4),
                    "source_url": SINA_PAGE,
                    "source_name": "新浪财经中证2000公开行情",
                    "previous_close": previous_close,
                    "quality_note": "主流媒体次级行情代理；指数定义仍以中证指数官方编制方案为准。"
                }
            ]
        }
