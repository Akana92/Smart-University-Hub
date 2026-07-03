"""
Загрузка исходных PDF вуза по конфигу (configs/<tenant>.yaml) → data/<tenant>/raw/.
SSL-aware: у kbtu.edu.kz в некоторых окружениях неполная цепочка сертификатов —
пробуем строгую проверку, при SSLError повторяем без проверки и помечаем ssl_insecure=true
(для публичных документов приёмной комиссии риск низкий; факт фиксируется в провенансе).

Использование:
    python ingestion/download_kbtu.py --config configs/kbtu.yaml
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import requests
import urllib3
import yaml

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
urllib3.disable_warnings()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "Mozilla/5.0 (SmartUniversity ingestion; contact akana92@gmail.com)"


def fetch(session, url):
    """(content_bytes, ssl_insecure). Сначала строгая проверка, затем фолбэк."""
    try:
        r = session.get(url, timeout=60, verify=True)
        r.raise_for_status()
        return r.content, False
    except requests.exceptions.SSLError:
        r = session.get(url, timeout=60, verify=False)
        r.raise_for_status()
        return r.content, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    cfg = yaml.safe_load(open(os.path.join(ROOT, args.config), encoding="utf-8"))
    tenant = cfg["tenant_id"]
    raw_dir = os.path.join(ROOT, "data", tenant, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/pdf"})
    manifest = []
    for s in cfg["sources"]:
        url, fname = s["url"], s["file"]
        dest = os.path.join(raw_dir, fname)
        try:
            content, insecure = fetch(session, url)
            if not content.startswith(b"%PDF"):
                raise ValueError("не PDF (нет magic %PDF)")
            with open(dest, "wb") as f:
                f.write(content)
            rec = {
                "file": fname, "url": url, "path": dest,
                "size_kb": len(content) // 1024,
                "file_hash": "sha256:" + hashlib.sha256(content).hexdigest(),
                "fetch_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "ssl_insecure": insecure, "scanned": s.get("scanned", False), "status": "ok",
            }
            print(f"[OK]   {fname}: {rec['size_kb']} KB{' (ssl-insecure)' if insecure else ''}"
                  f"{' [SCAN→OCR]' if rec['scanned'] else ''}")
        except Exception as e:  # noqa: BLE001
            rec = {"file": fname, "url": url, "status": "FAIL", "error": str(e)}
            print(f"[FAIL] {fname}: {e}")
        manifest.append(rec)

    man_path = os.path.join(ROOT, "data", tenant, "download_manifest.json")
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    ok = sum(1 for r in manifest if r.get("status") == "ok")
    print(f"\nСкачано {ok}/{len(manifest)} → {raw_dir}\nManifest: {man_path}")


if __name__ == "__main__":
    main()
