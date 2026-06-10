"""order_check が TRADE_DISABLED を返す原因を切り分ける（実発注なし）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import MetaTrader5 as mt5
from mt5_mcp.connection import mt

m = mt()  # 既存の接続ロジックで initialize

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "USDJPY"

ai = m.account_info()
print("--- account_info ---")
print("login:", ai.login, "balance:", ai.balance, "trade_allowed:", ai.trade_allowed,
      "trade_expert:", ai.trade_expert, "trade_mode:", ai.trade_mode, "margin_mode:", ai.margin_mode)

ti = m.terminal_info()
print("trade_allowed(terminal):", ti.trade_allowed, "connected:", ti.connected)

si = m.symbol_info(SYMBOL)
print("\n--- symbol_info ---")
print("visible:", si.visible, "trade_mode:", si.trade_mode,
      "filling_mode(raw):", si.filling_mode, "expiration_mode:", si.expiration_mode,
      "volume_min:", si.volume_min, "volume_step:", si.volume_step)
if not si.visible:
    m.symbol_select(SYMBOL, True)
    si = m.symbol_info(SYMBOL)

tick = m.symbol_info_tick(SYMBOL)
price = tick.ask

base = {
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": SYMBOL,
    "volume": si.volume_min,
    "type": mt5.ORDER_TYPE_BUY,
    "price": price,
    "deviation": 20,
    "magic": 20260610,
    "comment": "dbg",
    "type_time": mt5.ORDER_TIME_GTC,
}

print("\n--- order_check: filling モード別 ---")
for label, fill in [
    ("IOC", mt5.ORDER_FILLING_IOC),
    ("FOK", mt5.ORDER_FILLING_FOK),
    ("RETURN", mt5.ORDER_FILLING_RETURN),
    ("(no type_filling)", None),
]:
    req = dict(base)
    if fill is not None:
        req["type_filling"] = fill
    r = m.order_check(req)
    if r is None:
        print(f"{label:18s}: None  last_error={m.last_error()}")
    else:
        print(f"{label:18s}: retcode={r.retcode} comment={r.comment!r} balance={r.balance} margin={r.margin}")

# trade_mode の意味
modes = {0: "DISABLED", 1: "LONGONLY", 2: "SHORTONLY", 3: "CLOSEONLY", 4: "FULL"}
print("\nsymbol trade_mode =", si.trade_mode, modes.get(si.trade_mode, "?"))
acc_modes = {0: "DISABLED", 1: "LONGONLY", 2: "SHORTONLY", 3: "CLOSEONLY", 4: "FULL"}
print("account trade_mode =", ai.trade_mode, "(0=demo,1=contest,2=real)")
