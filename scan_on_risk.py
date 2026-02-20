import sqlite3
import asyncio
import aiohttp
import csv
import json
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import statistics

BINANCE_BASE = "https://fapi.binance.com"
DB_PATH = "scan_results.sqlite"
ADVANCED_CSV_PATH = "scan_advanced_results.csv"
GRADES_JSON_PATH = "scan_grades.json"

# Grade thresholds
VOLATILITY_THRESHOLDS = {  # ATR % thresholds
    "A": (0, 2.0),
    "B": (2.0, 5.0),
    "C": (5.0, 10.0),
    "D": (10.0, 100.0),
}

OI_THRESHOLDS = {  # OI USDT thresholds
    "A": (10_000_000, float('inf')),
    "B": (6_000_000, 10_000_000),
    "C": (4_000_000, 6_000_000),
    "D": (0, 4_000_000),
}

ORDERBOOK_GRADE_WEIGHTS = {  # Spread + depth balance
    "A": (0, 0.05),      # <0.05% spread, balanced
    "B": (0.05, 0.15),   # <0.15% spread
    "C": (0.15, 0.50),   # <0.5% spread (thin)
    "D": (0.50, 100.0),  # >0.5% spread (very thin)
}


async def http_get_async(url: str, params: Optional[Dict] = None, timeout: int = 20) -> Optional[Dict]:
    """Async HTTP GET with error handling"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params or {}, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status == 200:
                    return await r.json()
    except Exception as e:
        print(f"API Error on {url}: {e}")
    return None


def load_latest_scan(db_path: str) -> List[Dict]:
    """Load latest scan results from database"""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    
    # Get latest run_id
    latest_run = con.execute("""
        SELECT run_id FROM scan_runs ORDER BY run_ts DESC LIMIT 1
    """).fetchone()
    
    if not latest_run:
        print("No scan results found in database")
        return []
    
    run_id = latest_run['run_id']
    
    # Get all signals from latest run
    signals = con.execute("""
        SELECT 
            symbol, setup, oi_usdt,
            top_acc_long, top_acc_short,
            glob_acc_long, glob_acc_short,
            top_pos_long, top_pos_short,
            funding_rate, current_price, volume_24h, volume_2h
        FROM scan_hits
        WHERE run_id = ?
        ORDER BY oi_usdt DESC
    """, (run_id,)).fetchall()
    
    con.close()
    return [dict(s) for s in signals]


async def get_volatility(symbol: str, interval: str = "1m", periods: int = 14) -> Optional[Dict]:
    """Calculate ATR-based volatility"""
    try:
        url = f"{BINANCE_BASE}/fapi/v1/klines"
        params = {"symbol": symbol, "interval": interval, "limit": periods + 5}
        
        data = await http_get_async(url, params)
        if not data or len(data) < periods:
            return None
        
        true_ranges = []
        for i in range(1, len(data)):
            high = float(data[i][2])
            low = float(data[i][3])
            prev_close = float(data[i-1][4])
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        atr = statistics.mean(true_ranges[-periods:])
        current_price = float(data[-1][4])
        atr_pct = (atr / current_price) * 100
        
        return {
            "atr": atr,
            "atr_pct": atr_pct,
            "current_price": current_price,
            "grade": grade_volatility(atr_pct)
        }
    except Exception as e:
        print(f"Volatility error for {symbol}: {e}")
        return None


def grade_volatility(atr_pct: float) -> str:
    """Grade volatility A-D"""
    if atr_pct < 2.0:
        return "A"
    elif atr_pct < 5.0:
        return "B"
    elif atr_pct < 10.0:
        return "C"
    else:
        return "D"


async def get_order_book(symbol: str, depth: int = 20) -> Optional[Dict]:
    """Analyze order book depth and spread"""
    try:
        url = f"{BINANCE_BASE}/fapi/v1/depth"
        params = {"symbol": symbol, "limit": depth}
        
        data = await http_get_async(url, params)
        if not data or "bids" not in data or "asks" not in data:
            return None
        
        bids = [[float(p), float(q)] for p, q in data["bids"]]
        asks = [[float(p), float(q)] for p, q in data["asks"]]
        
        if not bids or not asks:
            return None
        
        # Calculate metrics
        best_bid = bids[0][0]
        best_ask = asks[0][0]
        mid_price = (best_bid + best_ask) / 2
        
        spread = ((best_ask - best_bid) / mid_price) * 100
        
        # Check bid/ask balance (sum of top 5 each side)
        bid_volume = sum(q for p, q in bids[:5])
        ask_volume = sum(q for p, q in asks[:5])
        total_volume = bid_volume + ask_volume
        
        if total_volume > 0:
            bid_ratio = bid_volume / total_volume
        else:
            bid_ratio = 0.5
        
        imbalance = abs(bid_ratio - 0.5) * 100  # 0-50, 0 is balanced
        
        # Grade based on spread
        grade = grade_spread(spread)
        
        return {
            "spread_pct": spread,
            "bid_ask_imbalance": imbalance,
            "bid_ratio": bid_ratio,
            "mid_price": mid_price,
            "grade": grade
        }
    except Exception as e:
        print(f"Order book error for {symbol}: {e}")
        return None


def grade_spread(spread_pct: float) -> str:
    """Grade order book based on spread"""
    if spread_pct < 0.05:
        return "A"
    elif spread_pct < 0.15:
        return "B"
    elif spread_pct < 0.50:
        return "C"
    else:
        return "D"


async def detect_drawdown_pattern(symbol: str, lookback_candles: int = 120) -> Optional[Dict]:
    """
    Detect heavy downside candles (>0.5% down in 1min)
    Flag stop-hunt patterns (repeated downs)
    """
    try:
        url = f"{BINANCE_BASE}/fapi/v1/klines"
        params = {"symbol": symbol, "interval": "1m", "limit": lookback_candles}
        
        data = await http_get_async(url, params)
        if not data or len(data) < 20:
            return None
        
        heavy_down_count = 0
        consecutive_down_count = 0
        max_consecutive = 0
        down_pcts = []
        
        for i in range(len(data)):
            open_price = float(data[i][1])
            close_price = float(data[i][4])
            
            pct_change = ((close_price - open_price) / open_price) * 100
            
            if pct_change < -0.5:  # Heavy down
                heavy_down_count += 1
                consecutive_down_count += 1
                down_pcts.append(pct_change)
            else:
                if consecutive_down_count > max_consecutive:
                    max_consecutive = consecutive_down_count
                consecutive_down_count = 0
        
        final_consecutive = consecutive_down_count
        if final_consecutive > max_consecutive:
            max_consecutive = final_consecutive
        
        # Calculate average down move for heavy downside
        avg_down_pct = statistics.mean(down_pcts) if down_pcts else 0
        
        # Grade drawdown risk
        grade = grade_drawdown(heavy_down_count, max_consecutive, lookback_candles)
        
        # Flag stop-hunt if pattern is obvious
        stop_hunt_risk = "YES" if max_consecutive >= 3 else "CAUTION" if max_consecutive == 2 else "NO"
        
        return {
            "heavy_down_count": heavy_down_count,
            "heavy_down_ratio": (heavy_down_count / lookback_candles) * 100,
            "max_consecutive_down": max_consecutive,
            "avg_down_pct": avg_down_pct,
            "grade": grade,
            "stop_hunt_risk": stop_hunt_risk
        }
    except Exception as e:
        print(f"Drawdown error for {symbol}: {e}")
        return None


def grade_drawdown(heavy_down_count: int, max_consecutive: int, total_candles: int) -> str:
    """Grade drawdown risk A-D"""
    ratio = (heavy_down_count / total_candles) * 100
    
    # A: <5% heavy downs, max 1 consecutive
    if ratio < 5 and max_consecutive <= 1:
        return "A"
    # B: 5-10% heavy downs, max 2 consecutive
    elif ratio < 10 and max_consecutive <= 2:
        return "B"
    # C: 10-20% heavy downs or 3 consecutive
    elif ratio < 20 or max_consecutive <= 3:
        return "C"
    else:
        return "D"


def grade_oi(oi_usdt: float) -> str:
    """Grade open interest"""
    if oi_usdt >= 10_000_000:
        return "A"
    elif oi_usdt >= 6_000_000:
        return "B"
    elif oi_usdt >= 4_000_000:
        return "C"
    else:
        return "D"


def calculate_final_grade(grades: Dict[str, str]) -> str:
    """Calculate overall grade from component grades"""
    grade_values = {"A": 4, "B": 3, "C": 2, "D": 1}
    values = [grade_values.get(g, 1) for g in grades.values()]
    
    if not values:
        return "D"
    
    avg = statistics.mean(values)
    
    if avg >= 3.5:
        return "A"
    elif avg >= 2.5:
        return "B"
    elif avg >= 1.5:
        return "C"
    else:
        return "D"


async def analyze_coin(signal: Dict) -> Dict:
    """Full analysis of a signal coin"""
    symbol = signal["symbol"]
    setup = signal["setup"]
    oi_usdt = signal["oi_usdt"]
    
    print(f"Analyzing {symbol} ({setup})...", end=" ", flush=True)
    
    # Parallel analysis tasks
    volatility_task = asyncio.create_task(get_volatility(symbol))
    orderbook_task = asyncio.create_task(get_order_book(symbol))
    drawdown_task = asyncio.create_task(detect_drawdown_pattern(symbol))
    
    volatility = await volatility_task
    orderbook = await orderbook_task
    drawdown = await drawdown_task
    
    # Build result
    result = {
        "symbol": symbol,
        "setup": setup,
        "oi_usdt": oi_usdt,
        "funding_rate": signal.get("funding_rate"),
        "current_price": signal.get("current_price"),
        "volume_24h": signal.get("volume_24h"),
        "volume_2h": signal.get("volume_2h"),
    }
    
    # Grade each metric
    grades = {}
    
    if volatility:
        result["volatility_atr_pct"] = volatility["atr_pct"]
        grades["volatility"] = volatility["grade"]
    else:
        result["volatility_atr_pct"] = None
        grades["volatility"] = "D"
    
    if orderbook:
        result["spread_pct"] = orderbook["spread_pct"]
        result["bid_ask_imbalance"] = orderbook["bid_ask_imbalance"]
        grades["orderbook"] = orderbook["grade"]
    else:
        result["spread_pct"] = None
        result["bid_ask_imbalance"] = None
        grades["orderbook"] = "D"
    
    grades["oi"] = grade_oi(oi_usdt)
    
    if drawdown:
        result["heavy_down_ratio"] = drawdown["heavy_down_ratio"]
        result["max_consecutive_down"] = drawdown["max_consecutive_down"]
        result["stop_hunt_risk"] = drawdown["stop_hunt_risk"]
        grades["drawdown"] = drawdown["grade"]
    else:
        result["heavy_down_ratio"] = None
        result["max_consecutive_down"] = None
        result["stop_hunt_risk"] = "UNKNOWN"
        grades["drawdown"] = "D"
    
    result["grades"] = grades
    result["final_grade"] = calculate_final_grade(grades)
    result["risk_level"] = get_risk_level(result["final_grade"])
    
    print(f"✓ Grade: {result['final_grade']}")
    return result


def get_risk_level(grade: str) -> str:
    """Convert grade to risk level"""
    if grade == "A":
        return "LOW"
    elif grade == "B":
        return "MEDIUM"
    elif grade == "C":
        return "HIGH"
    else:
        return "VERY_HIGH"


async def analyze_all(signals: List[Dict]) -> List[Dict]:
    """Analyze all signals with rate limiting"""
    results = []
    
    for signal in signals:
        result = await analyze_coin(signal)
        results.append(result)
        await asyncio.sleep(0.5)  # Rate limit
    
    return results


def export_to_csv(results: List[Dict]):
    """Export analysis to CSV"""
    with open(ADVANCED_CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        
        # Header
        writer.writerow([
            'Symbol', 'Setup', 'OI (USDT)',
            'Volatility %', 'Vol Grade',
            'Spread %', 'Imbalance %', 'OB Grade',
            'OI Grade', 'Heavy Downs %', 'Max Cons Down', 'Drawdown Grade',
            'Stop Hunt Risk',
            'Final Grade', 'Risk Level',
            'Funding Rate', 'Price', '24h Vol', '2h Vol'
        ])
        
        # Sort by final grade and OI
        sorted_results = sorted(
            results,
            key=lambda x: (x['final_grade'], -x['oi_usdt']),
            reverse=False  # A before D
        )
        
        for r in sorted_results:
            writer.writerow([
                r['symbol'],
                r['setup'],
                f"{r['oi_usdt']:,.0f}",
                f"{r['volatility_atr_pct']:.2f}%" if r['volatility_atr_pct'] is not None else "N/A",
                r['grades'].get('volatility', '?'),
                f"{r['spread_pct']:.4f}%" if r['spread_pct'] is not None else "N/A",
                f"{r['bid_ask_imbalance']:.1f}%" if r['bid_ask_imbalance'] is not None else "N/A",
                r['grades'].get('orderbook', '?'),
                r['grades']['oi'],
                f"{r['heavy_down_ratio']:.1f}%" if r['heavy_down_ratio'] is not None else "N/A",
                r['max_consecutive_down'] if r['max_consecutive_down'] is not None else "N/A",
                r['grades'].get('drawdown', '?'),
                r['stop_hunt_risk'],
                r['final_grade'],
                r['risk_level'],
                f"{r['funding_rate']*100:.4f}%" if r['funding_rate'] is not None else "N/A",
                f"${r['current_price']:.2f}" if r['current_price'] is not None else "N/A",
                f"{r['volume_24h']:,.0f}" if r['volume_24h'] is not None else "N/A",
                f"{r['volume_2h']:,.0f}" if r['volume_2h'] is not None else "N/A",
            ])
    
    print(f"\n✅ CSV exported to: {ADVANCED_CSV_PATH}")


def export_grades_json(results: List[Dict]):
    """Export detailed grades as JSON"""
    grades_obj = {
        "generated": datetime.now().isoformat(),
        "total_coins": len(results),
        "coins": {}
    }
    
    for r in results:
        grades_obj["coins"][r['symbol']] = {
            "setup": r['setup'],
            "oi_usdt": r['oi_usdt'],
            "grades": r['grades'],
            "final_grade": r['final_grade'],
            "risk_level": r['risk_level'],
            "metrics": {
                "volatility_atr_pct": r['volatility_atr_pct'],
                "spread_pct": r['spread_pct'],
                "heavy_down_ratio": r['heavy_down_ratio'],
                "stop_hunt_risk": r['stop_hunt_risk'],
            }
        }
    
    with open(GRADES_JSON_PATH, 'w') as f:
        json.dump(grades_obj, f, indent=2)
    
    print(f"✅ Grades JSON exported to: {GRADES_JSON_PATH}")


def print_summary(results: List[Dict]):
    """Print analysis summary"""
    grades_count = {"A": 0, "B": 0, "C": 0, "D": 0}
    risk_count = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "VERY_HIGH": 0}
    
    for r in results:
        grades_count[r['final_grade']] += 1
        risk_count[r['risk_level']] += 1
    
    print(f"\n{'='*60}")
    print(f"Advanced Analysis Summary")
    print(f"{'='*60}")
    print(f"Total coins analyzed: {len(results)}")
    print(f"\nGrades distribution:")
    print(f"  A (PRIME_ENTRY): {grades_count['A']}")
    print(f"  B (GOOD_ENTRY): {grades_count['B']}")
    print(f"  C (CAUTION_ENTRY): {grades_count['C']}")
    print(f"  D (FLAG_REVIEW): {grades_count['D']}")
    print(f"\nRisk distribution:")
    print(f"  LOW: {risk_count['LOW']}")
    print(f"  MEDIUM: {risk_count['MEDIUM']}")
    print(f"  HIGH: {risk_count['HIGH']}")
    print(f"  VERY_HIGH: {risk_count['VERY_HIGH']}")
    
    # Show top A grades
    a_coins = [r for r in results if r['final_grade'] == 'A']
    if a_coins:
        print(f"\n⭐ Best Entry Opportunities (Grade A):")
        for r in sorted(a_coins, key=lambda x: -x['oi_usdt'])[:5]:
            print(f"  {r['symbol']:10} {r['setup']:25} OI: ${r['oi_usdt']/1e6:.1f}M")


async def main():
    print("Loading scan results...")
    signals = load_latest_scan(DB_PATH)
    
    if not signals:
        return
    
    # Filter: Only analyze coins with OI >= 4M
    filtered_signals = [s for s in signals if s.get("oi_usdt", 0) >= 4_000_000]
    skipped = len(signals) - len(filtered_signals)
    
    print(f"Found {len(signals)} signals total")
    if skipped > 0:
        print(f"Skipping {skipped} coins with OI < 4M")
    print(f"Analyzing {len(filtered_signals)} coins with OI >= 4M...\n")
    
    if not filtered_signals:
        print("No coins meet the OI >= 4M requirement")
        return
    
    results = await analyze_all(filtered_signals)
    
    # Export results
    export_to_csv(results)
    export_grades_json(results)
    
    # Print summary
    print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
