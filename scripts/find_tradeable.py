"""取引可能(trade_mode=FULL)なシンボルを探す。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from mt5_mcp.connection import mt

m = mt()
modes = {0: "DISABLED", 1: "LONGONLY", 2: "SHORTONLY", 3: "CLOSEONLY", 4: "FULL"}

all_syms = m.symbols_get()
print("総シンボル数:", len(all_syms))

by_mode = {}
tradeable = []
for s in all_syms:
    by_mode[s.trade_mode] = by_mode.get(s.trade_mode, 0) + 1
    if s.trade_mode == 4:
        tradeable.append(s.name)

print("trade_mode 分布:", {modes.get(k, k): v for k, v in sorted(by_mode.items())})
print("\n取引可能(FULL)シンボル数:", len(tradeable))
print("例:", tradeable[:40])

# JPY/USD系で取引可能なものを抽出
fx = [n for n in tradeable if any(c in n.upper() for c in ("JPY", "USD", "EUR", "GBP"))]
print("\nFX系(取引可能)例:", fx[:40])
