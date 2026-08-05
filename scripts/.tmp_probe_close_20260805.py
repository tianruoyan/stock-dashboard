import json
import akshare as ak

out = {}
for name, fn in [
    ("zt", lambda: ak.stock_zt_pool_em(date="20260805")),
    ("dt", lambda: ak.stock_zt_pool_dtgc_em(date="20260805")),
    ("zb", lambda: ak.stock_zt_pool_zbgc_em(date="20260805")),
]:
    try:
        df = fn()
        out[name] = {"count": len(df), "columns": list(df.columns), "head": df.head(3).to_dict("records")}
    except Exception as exc:
        out[name] = {"error": repr(exc)}

print(json.dumps(out, ensure_ascii=False, default=str))
