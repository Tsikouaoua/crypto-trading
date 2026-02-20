# Scanner Theory - Condensed

## Setup A & B (Contrarian Signals)

**Setup A: Crowd SHORT, Top Traders LONG**
- Retail heavily short (>65%), professionals long (>45%)
- Signal: Crowd is wrong

**Setup B: Crowd LONG, Top Traders SHORT**
- Retail heavily long (>65%), professionals short (>45%)
- Signal: Crowd is wrong

---

## scan_enhanced.py Process

```
1. Check trader ratios (cheap API calls)
2. Filter by OI >= 2.5M (minimum liquidity)
3. Get funding rate + price
4. Get 24h volume + latest 2h volume

→ Store in database + export CSV (with funding highlights)
```

---

## scan_advanced.py - 4 Metrics

### 1. Volatility (ATR % on 1-min)
```
A = <2%  (smooth)
B = 2-5% (normal)
C = 5-10% (risky)
D = >10% (avoid)
```

### 2. Order Book (Spread %)
```
A = <0.05%  (liquid)
B = <0.15%  (good)
C = <0.5%   (thin)
D = >0.5%   (very thin)
```

### 3. Open Interest (OI USDT)
```
A = ≥10M (very liquid)
B = ≥6M  (good)
C = ≥4M  (minimum - YOUR FILTER)
D = <4M  (risky)
```

### 4. Drawdown Pattern (1-min candles)
```
Heavy down candles (>0.5% down) + consecutive patterns
→ Indicates stop-hunt risk before real move

A = <5% heavy downs     (safe)
B = 5-10%              (normal)
C = 10-20% or 3+ down  (caution)
D = >20% or 4+ down    (stop hunt obvious)
```

---

## Final Grade Calculation

```
Final = Average(Vol_Grade, OrderBook_Grade, OI_Grade, Drawdown_Grade)

A = 3.5+  (mostly A's/B's)  → PRIME_ENTRY
B = 2.5+  (mix A/B/C)       → GOOD_ENTRY
C = 1.5+  (mostly C's)      → CAUTION
D = <1.5  (has D's)         → SKIP
```

---

## Position Sizing by Grade

| Grade | Trade? | Risk | Position |
|-------|--------|------|----------|
| **A** | YES | LOW | FULL |
| **B** | YES | MEDIUM | FULL |
| **C** | CAUTION | HIGH | HALF |
| **D** | NO | VERY_HIGH | 0 |

---

## Why Each Metric Matters

**Volatility**: Tells you stop-loss size. High ATR = need wide stops = larger risk.

**Order Book**: Thin book = slippage on entry/exit. Can't exit when you want if book is thin.

**OI ≥4M**: Your cutoff. Below this = not enough traders/positions = hard to move in/out. Also liquidation cascades more likely if thin.

**Drawdown Pattern**: Stop-hunt indicator. If professionals are repeatedly pushing price down before entry, they'll do it at your entry too. Risk for no reason.

---

## Setup A vs Setup B

**SETUP A (Crowd SHORT → You LONG):**
- Risk: Downside stop-hunts
- Watch: Heavy red 1-min candles before entry
- These are shorts testing where your stops are

**SETUP B (Crowd LONG → You SHORT):**
- Risk: Upside fakeouts
- Watch: Heavy green 1-min candles before entry
- These are shorts covering, shaking out longs

---

## Key Rule

**Only trade OI ≥ 4M USDT**

Below that, liquidity is too risky. Even if other metrics are good, thin OI means:
- Slippage on entry/exit
- Easy for big traders to liquidate retail
- Harder to scale position

---

## Example Grades

```
BNBUSDT: Vol=A, Book=B, OI=A, Drawdown=A → Final=A (PRIME)
ETHUSDT: Vol=B, Book=C, OI=B, Drawdown=C → Final=B (GOOD)
SOLUSDT: Vol=C, Book=D, OI=D, Drawdown=B → Final=D (SKIP - has D)
```

The presence of any D grade usually means skip (unless extremely high conviction).
