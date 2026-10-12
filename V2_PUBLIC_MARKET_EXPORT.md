# V2 intraday freshness and public market export

V2 remains shadow-only. These changes do not install or enable any Mac service, acquire market data, publish a Git commit, or change V1.

## Intraday runner

`scripts/run_v22_intraday_shadow.py` delegates all calendar, Asia/Shanghai timezone, and checkpoint decisions to `V22IntradayShadowRunner`. The entire configured end minute is included, including 15:20:59 for close freeze. Exchange holidays and unverified calendar periods remain closed even with `--force-checkpoint`.

A zero process exit does not prove fresh market data. Market runs now require updated producer artifacts, verified same-day source timestamps, and a collector result that did not retain old facts. Future timestamps, stale/missing outputs, and newly rebuilt reports with old source timestamps produce `waiting_update`, leave the checkpoint retryable, and exit nonzero. Close freeze specifically requires source evidence from 15:00 or later. Report generation times never refresh market evidence. Pre-open status-only runs report that no market data was refreshed.

## Narrow local export

Preview (default, no writes):

    python3 scripts/export_v2_public_market.py --source /path/to/runtime --target /path/to/public-share

Apply only the approved local output after reviewing the preview:

    python3 scripts/export_v2_public_market.py --source /path/to/runtime --target /path/to/public-share --apply

The source and target must be separate directories. The tool performs no network, Git, installation, or acquisition operations. It is not connected to a scheduler automatically.

### Approved scope

The only output is `data/v2/v22/market-environment.json`, marked `partial_public_facts` and `decision_readiness: false`. It is reconstructed from public breadth and liquidity collector files. Only validated counts, turnover, fixed public source identifiers, and original source timestamps are retained. Display text is static or derived from validated numbers. No private holdings, personal pools, notes, credentials, blogger content, source URLs, arbitrary text, or nested source objects are copied.

This two-dimension facts view cannot establish market action, candidate readiness, or model promotion. The report lists the seven other existing public projections as unapproved and preserves their bytes. A future broader exporter requires a separate field-level privacy and provenance review.

### Fail-closed behavior

Missing/malformed data, unverified public provenance, unknown sources, inconsistent counts/snapshots, future timestamps, or source data older than 30 minutes prevent export. Build times do not confer freshness. Existing equal/newer output or a newer individual published source is retained. An unreadable or undated existing output is also retained for review. Source/destination symlinks are rejected. Writes use a lock and atomic replacement of the one approved JSON file.

## Verification

    python3 -m unittest discover -s tests -p test_v22_intraday_shadow.py -v
    python3 -m unittest discover -s tests -p test_v2_public_market_export.py -v

Tests use temporary fixtures and fake commands; they do not execute live producers or change current public data. Restoring live freshness still requires the authorized connected runtime, verified live inputs, and separately approved publication. This CLI cannot reconnect a Mac, install a scheduler, generate current facts, or refresh the seven remaining projections.
