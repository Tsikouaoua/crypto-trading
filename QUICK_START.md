# Quick Start Guide

## Two-Script Workflow

### Step 1: Run Main Scanner (finds trader conflicts)
```bash
python scan_enhanced.py
```
**What it does:**
- Scans all 1000+ USDT perpetual coins on Binance
- Finds where crowd traders are wrong (crowd SHORT but top traders LONG, etc)
- Filters by minimum OI (2.5M)
- Stores results in database + exports CSV

**Output files:**
- `scan_results.sqlite` - Database (keeps history)
- `scan_results.csv` - Human-readable results with funding highlights

**Time:** 2-5 minutes

---

### Step 2: Run Advanced Analysis (grades the signals)
```bash
python scan_advanced.py
```
**What it does:**
- Reads the coins from step 1
- Analyzes each coin for:
  - **Volatility** (ATR 14-period, lower is safer)
  - **Order Book** (spread, depth balance)
  - **Open Interest** (>4M is best)
  - **Drawdown Pattern** (detects stop-hunt risk)
- Grades A/B/C/D for each metric
- Calculates final grade (A = safest entry)

**Output files:**
- `scan_advanced_results.csv` - CSV with all grades + metrics
- `scan_grades.json` - Detailed breakdown (programmatic use)

**Time:** 30 seconds to 2 minutes (depends on number of signals)

---

## Grading System (A=Best, D=Avoid)

### What Each Grade Means

| Grade | Entry Decision | Risk Level |
|-------|---|---|
| **A** | STRONG BUY - Low risk, good liquidity | LOW |
| **B** | BUY - Safe entry, normal conditions | MEDIUM |
| **C** | CAUTION - Check manually first | HIGH |
| **D** | SKIP - Too risky or data issues | VERY_HIGH |

### How Final Grade is Calculated

```
Final Grade = Average(Volatility_Grade, OrderBook_Grade, OI_Grade, Drawdown_Grade)

A = 3.5+ (mostly A's and B's)
B = 2.5+ (mix of A,B,C)
C = 1.5-2.5 (mostly C's)
D = <1.5 (has D's or all C's)
```

---

## Understanding Each Metric

### 1. Volatility (ATR %)
- **What**: Average True Range as % of price (14-period 1-min)
- **Why**: Tells you how much the coin moves on average
- **Grades:**
  - A: <2% (smooth, predictable)
  - B: 2-5% (normal)
  - C: 5-10% (volatile, risky)
  - D: >10% (very volatile, avoid)

### 2. Order Book (Spread %)
- **What**: Bid-ask spread and depth balance
- **Why**: Shows if the market is liquid (tight) or thin (wide spreads)
- **Grades:**
  - A: <0.05% spread (liquid market)
  - B: <0.15% (good)
  - C: <0.5% (thin, watch slippage)
  - D: >0.5% (very thin, risky)

### 3. Open Interest (OI)
- **What**: Total amount of open contracts in USDT
- **Why**: Higher OI = more liquidity, easier to enter/exit
- **Grades:**
  - A: ≥10M USDT
  - B: ≥6M USDT
  - C: ≥4M USDT (minimum)
  - D: <4M (risky liquidity)

### 4. Drawdown Pattern (1-min candles)
- **What**: Heavy downside candles (>0.5% down) and repetition patterns
- **Why**: Repeated heavy downs = stop-hunt risk before real move
- **Special**: For CROWD_SHORT (wanting to LONG), this is critical
- **Grades:**
  - A: <5% heavy downs, no repetition (safe)
  - B: 5-10% heavy downs, ≤2 in a row
  - C: 10-20% heavy downs, ≤3 in a row, some repetition
  - D: >20% heavy downs or ≥3 in a row (obvious stop hunt)
- **Stop Hunt Risk:**
  - YES = 3+ consecutive down candles (clear pattern)
  - CAUTION = 2 consecutive down candles (possible)
  - NO = 0-1 down candle in any row (safe)

---

## Using the CSV Output

### Column Guide (scan_advanced_results.csv)

```
Symbol          = Coin ticker (e.g., BTCUSDT)
Setup           = CROWD_SHORT__TOP_LONG or CROWD_LONG__TOP_SHORT
OI (USDT)       = Open interest (want ≥4M)
Volatility %    = ATR as % of price (lower is safer)
Vol Grade       = A/B/C/D for volatility
Spread %        = Bid-ask spread (lower is better)
Imbalance %     = Bid/ask order balance (0% = balanced)
OB Grade        = A/B/C/D for order book
OI Grade        = A/B/C/D for open interest
Heavy Downs %   = % of 1-min candles with >0.5% downside
Max Cons Down   = Longest streak of down candles
Drawdown Grade  = A/B/C/D for drawdown risk
Stop Hunt Risk  = YES/CAUTION/NO
Final Grade     = Your overall grade (A/B/C/D)
Risk Level      = LOW/MEDIUM/HIGH/VERY_HIGH
```

---

## Decision Rules

### ✅ GOOD ENTRIES (Grade A or B)

1. Setup is correct (CROWD_SHORT for long, CROWD_LONG for short)
2. Final Grade is A or B
3. OI ≥ 4M (Grade C or better)
4. Stop Hunt Risk = NO or CAUTION
5. Order Book Grade = A or B (not thin)

**Position Size:** FULL

### ⚠️ CAUTION ENTRIES (Grade C)

1. Check the setup manually (watch 5-min chart)
2. Verify order book has actual depth
3. If Stop Hunt Risk = YES, only micro position
4. Tighter stop loss than usual

**Position Size:** HALF

### ❌ SKIP (Grade D or multiple D's)

1. Data quality issues
2. Volatility too high (>10%)
3. Order book too thin (>0.5% spread)
4. OI too low (<4M)
5. Stop hunt pattern obvious

**Position Size:** 0 (or micro research position)

---

## Example from CSV

```csv
BNBUSDT,CROWD_SHORT__TOP_LONG,8500000,1.5%,A,0.03%,2%,A,A,3.5%,1,A,NO,A,LOW,...
↑       ↑ You want to LONG      ↑ Good space ↑ Smooth   ↑ Low spread ↑ Excellent OI

→ DECISION: STRONG BUY (Grade A)
→ Position: FULL
→ Stop Loss: Standard (e.g., 2-3 ATR below entry)
→ Risk: LOW
```

```csv
ETHUSDT,CROWD_LONG__TOP_SHORT,5200000,6.2%,C,0.25%,15%,B,B,12%,2,C,CAUTION,C,HIGH,...
↑       ↑ You want to SHORT     ↑ Normal ↑ Volatile ↑ OK spread ↑ Some heavy downs

→ DECISION: CAUTION (Grade C)
→ Position: HALF
→ Stop Loss: Tighter (1-2 ATR)
→ Risk: HIGH
→ Note: Check chart, 12% heavy downs = some stop hunt risk
```

```csv
SOLUSDT,CROWD_SHORT__TOP_LONG,3800000,9.5%,D,1.2%,45%,D,D,25%,4,D,YES,D,VERY_HIGH,...
↑       ↑ Want to LONG          ↑ Risky ↑ Very volatile ↑ Thin book ↑ Clear pattern

→ DECISION: SKIP (Grade D)
→ Position: 0 (or micro if strong bias)
→ Risk: VERY HIGH
→ Issues: Too volatile, thin book, obvious stop hunt (4 down candles in a row)
```

---

## Running Both Scripts (Full Workflow)

### Option 1: Manual (Best for Learning)
```bash
# Morning scan
python scan_enhanced.py
# Check results in scan_results.csv

# Then run advanced analysis
python scan_advanced.py
# Review grades in scan_advanced_results.csv
```

### Option 2: Automated (Batch File - Windows)
Create `run_analysis.bat`:
```batch
@echo off
echo Running scan...
python scan_enhanced.py
echo.
echo Running advanced analysis...
python scan_advanced.py
echo.
echo Done! Check scan_results.csv and scan_advanced_results.csv
pause
```

Then double-click `run_analysis.bat`

---

## Tips & Tricks

### Check Multiple Times During the Day
- Run scanner near liquidity times (NY open, Asia open, GMT reset)
- Compare grades across different times
- Coins that grade A multiple times = stronger signals

### Use OI Trend
- If same coin appears multiple days with rising OI = strengthening signal
- Falling OI = weakening (traders reducing positions)
- Database tracks history automatically

### Combine with Your ATH Database
- Grade A coins + Price near ATH from your ATH database = high risk
- Grade A coins + Price near support = better risk:reward

### Stop Hunt Pattern Special Cases
- CROWD_SHORT + Stop Hunt YES = Extra caution (traders hunting longs before pump)
- Multiple consecutive down candles = They're testing where your stops are
- Use wider stops or tighter entry targets in these cases

---

## Troubleshooting

### Script runs slow
- Normal: First run takes 2-5 min (1000+ symbols)
- If stuck: Check internet, Binance API status
- Restart if needed

### Missing data (N/A in columns)
- Volatility N/A = Insufficient data (new coin)
- Spread N/A = API rate limit (try again in 1 min)
- Grades become D = Treat as unsafe

### Database issues
- Delete `scan_results.sqlite` to start fresh
- Script auto-creates new database

### API Rate Limits
- Binance: ~1200 requests/min for data
- Scanner = ~5 calls per symbol
- Advanced = ~3 calls per signal
- Usually OK, but may slow down if >100 signals

---

## Next Steps

1. **First time:** Read [DOCUMENTATION.md](DOCUMENTATION.md) for full theory
2. **Run both scripts** and review a few Grade A coins manually
3. **Verify on 5-min chart** - do they look like good entries?
4. **Combine with your strategy** - test on paper trading first
5. **Track results** - which setup (A or B) works better for you?

---

## Quick Reference Commands

```bash
# Run scanner only
python scan_enhanced.py

# Run advanced analysis only (uses latest scan data)
python scan_advanced.py

# View latest CSV results
# Windows: start scan_results.csv
# Linux: xdg-open scan_results.csv
# Mac: open scan_results.csv

# View latest advanced results
# Windows: start scan_advanced_results.csv
```

---

## Database Queries (For Advanced Users)

If you want to export history or analyze past runs:

```python
import sqlite3

con = sqlite3.connect('scan_results.sqlite')

# Get all runs
con.execute("SELECT * FROM scan_runs").fetchall()

# Get all signals from specific run (run_id=1)
con.execute("""
    SELECT symbol, setup, oi_usdt, funding_rate, current_price 
    FROM scan_hits WHERE run_id=1 ORDER BY oi_usdt DESC
""").fetchall()

# See which coins appear in multiple runs
con.execute("""
    SELECT symbol, COUNT(*) as count 
    FROM scan_hits GROUP BY symbol 
    HAVING count > 1 ORDER BY count DESC
""").fetchall()

con.close()
```

