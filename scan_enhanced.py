import sqlite3
import time
import requests
import csv
import asyncio
import aiohttp
from typing import List, Dict, Any, Optional
from datetime import datetime

import certifi
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BINANCE_BASE = "https://fapi.binance.com"
DB_PATH = "scan_results.sqlite"
CSV_PATH = "scan_results.csv"

# ===== PARAMETERS =====
PERIOD = "5m"
MIN_OI_USDT = 2_500_000

# Setup A: crowd SHORT, top traders not short
TOP_ACC_SHORT_MIN = 0.65
GLOBAL_ACC_SHORT_MIN = 0.65
TOP_POS_LONG_MIN = 0.45

# Setup B: crowd LONG, top traders not long
TOP_ACC_LONG_MIN = 0.65
GLOBAL_ACC_LONG_MIN = 0.65
TOP_POS_SHORT_MIN = 0.45

# Funding confirmation thresholds (for highlighting)
FUNDING_CONFIRM_THRESHOLD = 0.01  # 0.01% = significant funding bias

SLEEP_S = 0.02  # minimal sleep with async concurrency
# ======================

# ---- Requests session with retries + timeouts (prevents hanging)
session = requests.Session()
retry = Retry(
    total=5,
    connect=5,
    read=5,
    backoff_factor=0.6,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
    raise_on_status=False,
)
adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
session.mount("https://", adapter)
session.mount("http://", adapter)


def http_get(path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 20):
    """
    timeout is READ timeout; connect timeout is fixed at 5s.
    Prevents hanging indefinitely on socket read.
    """
    r = session.get(
        BINANCE_BASE + path,
        params=params or {},
        timeout=(5, timeout),      # (connect_timeout, read_timeout)
        verify=certifi.where(),    # stable CA bundle
        headers={"User-Agent": "Mozilla/5.0"},
    )
    r.raise_for_status()
    return r.json()


async def http_get_async(session: aiohttp.ClientSession, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 20):
    """Async version of http_get"""
    url = BINANCE_BASE + path
    try:
        async with session.get(url, params=params or {}, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            if r.status == 200:
                return await r.json()
            else:
                return None
    except Exception:
        return None


def list_usdt_perp_symbols() -> List[str]:
    info = http_get("/fapi/v1/exchangeInfo")
    out = []
    for s in info.get("symbols", []):
        if (
            s.get("contractType") == "PERPETUAL"
            and s.get("quoteAsset") == "USDT"
            and s.get("status") == "TRADING"
        ):
            out.append(s["symbol"])
    return out


def latest(endpoint: str, symbol: str, period: str) -> Optional[Dict[str, Any]]:
    try:
        data = http_get(endpoint, {"symbol": symbol, "period": period, "limit": 1})
        if not isinstance(data, list) or not data:
            return None
        return data[0]
    except requests.exceptions.RequestException as e:
        print(f"Network error on {symbol} {endpoint}: {e}")
        return None


async def latest_async(session: aiohttp.ClientSession, endpoint: str, symbol: str, period: str) -> Optional[Dict[str, Any]]:
    """Async version of latest"""
    try:
        data = await http_get_async(session, endpoint, {"symbol": symbol, "period": period, "limit": 1})
        if not isinstance(data, list) or not data:
            return None
        return data[0]
    except Exception:
        return None


def get_premium_data(symbol: str) -> tuple[Optional[float], Optional[float]]:
    """Get funding rate AND current price in a single API call"""
    try:
        data = http_get("/fapi/v1/premiumIndex", {"symbol": symbol})
        if data:
            funding_rate = float(data.get("lastFundingRate")) if "lastFundingRate" in data else None
            current_price = float(data.get("markPrice")) if "markPrice" in data else None
            return funding_rate, current_price
    except Exception as e:
        print(f"Error getting premium data for {symbol}: {e}")
    return None, None


async def get_premium_data_async(session: aiohttp.ClientSession, symbol: str) -> tuple[Optional[float], Optional[float]]:
    """Async version of get_premium_data"""
    try:
        data = await http_get_async(session, "/fapi/v1/premiumIndex", {"symbol": symbol})
        if data:
            funding_rate = float(data.get("lastFundingRate")) if "lastFundingRate" in data else None
            current_price = float(data.get("markPrice")) if "markPrice" in data else None
            return funding_rate, current_price
    except Exception:
        pass
    return None, None


async def get_volume_data_async(session: aiohttp.ClientSession, symbol: str) -> tuple[Optional[float], Optional[float]]:
    """Get 24h volume and latest 2h candle volume"""
    volume_24h = None
    volume_2h = None
    
    try:
        # Get 24h volume from ticker
        ticker = await http_get_async(session, "/fapi/v1/ticker/24hr", {"symbol": symbol})
        if ticker and "volume" in ticker:
            volume_24h = float(ticker.get("volume"))
    except Exception:
        pass
    
    try:
        # Get latest 2h candle volume
        klines = await http_get_async(session, "/fapi/v1/klines", {"symbol": symbol, "interval": "2h", "limit": 1})
        if klines and len(klines) > 0:
            # klines format: [time, open, high, low, close, volume, close_time, quote_asset_volume, ...]
            volume_2h = float(klines[0][7])  # quote_asset_volume (in USDT)
    except Exception:
        pass
    
    return volume_24h, volume_2h





def f(x) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def init_db(con: sqlite3.Connection):
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("""
    CREATE TABLE IF NOT EXISTS scan_runs (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_ts INTEGER NOT NULL,
        period TEXT NOT NULL,
        min_oi_usdt REAL NOT NULL
    );
    """)
    con.execute("""
    CREATE TABLE IF NOT EXISTS scan_hits (
        run_id INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        setup TEXT NOT NULL,
        timestamp_ms INTEGER NOT NULL,
        oi_usdt REAL NOT NULL,

        top_acc_long REAL,
        top_acc_short REAL,
        glob_acc_long REAL,
        glob_acc_short REAL,
        top_pos_long REAL,
        top_pos_short REAL,
        
        funding_rate REAL,
        current_price REAL,
        volume_24h REAL,
        volume_2h REAL,

        PRIMARY KEY (run_id, symbol, setup)
    );
    """)
    con.commit()


def reset_db(con: sqlite3.Connection):
    # "From scratch" each run
    con.execute("DELETE FROM scan_hits;")
    con.execute("DELETE FROM scan_runs;")
    con.commit()


def create_run(con: sqlite3.Connection) -> int:
    ts = int(time.time())
    con.execute(
        "INSERT INTO scan_runs(run_ts, period, min_oi_usdt) VALUES (?,?,?)",
        (ts, PERIOD, MIN_OI_USDT),
    )
    con.commit()
    return int(con.execute("SELECT last_insert_rowid()").fetchone()[0])


def scan_and_store(con: sqlite3.Connection, run_id: int, symbols: List[str]) -> int:
    """Synchronous wrapper for async scan"""
    return asyncio.run(scan_and_store_async(con, run_id, symbols))


async def scan_and_store_async(con: sqlite3.Connection, run_id: int, symbols: List[str]) -> int:
    inserted = 0
    scanned = 0
    passed_traders = 0
    total_symbols = len(symbols)

    sql = """
    INSERT OR REPLACE INTO scan_hits (
        run_id, symbol, setup, timestamp_ms, oi_usdt,
        top_acc_long, top_acc_short,
        glob_acc_long, glob_acc_short,
        top_pos_long, top_pos_short,
        funding_rate, current_price, volume_24h, volume_2h
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """

    print(f"Starting scan of {total_symbols} symbols...")

    # Queue for database writes (serialized)
    insert_queue = asyncio.Queue()
    
    # Create async session with SSL verification
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Semaphore to limit concurrent requests to 10
        semaphore = asyncio.Semaphore(10)
        
        async def process_symbol(sym):
            nonlocal scanned, passed_traders
            
            async with semaphore:
                scanned += 1
                
                if scanned % 25 == 0:
                    print(f"Progress: {scanned}/{total_symbols} scanned | traders_pass={passed_traders} | rows={inserted}")
                
                try:
                    # ---- FIRST: Check traders ratios (cheapest API calls)
                    top_acc = await latest_async(session, "/futures/data/topLongShortAccountRatio", sym, PERIOD)
                    glob_acc = await latest_async(session, "/futures/data/globalLongShortAccountRatio", sym, PERIOD)
                    top_pos = await latest_async(session, "/futures/data/topLongShortPositionRatio", sym, PERIOD)
                    
                    if not top_acc or not glob_acc or not top_pos:
                        return

                    ta_long, ta_short = f(top_acc.get("longAccount")), f(top_acc.get("shortAccount"))
                    ga_long, ga_short = f(glob_acc.get("longAccount")), f(glob_acc.get("shortAccount"))
                    tp_long, tp_short = f(top_pos.get("longAccount")), f(top_pos.get("shortAccount"))

                    if None in (ta_long, ta_short, ga_long, ga_short, tp_long, tp_short):
                        return

                    ts_ms = int(top_acc.get("timestamp", 0))
                    
                    # Check if either Setup A or B applies
                    setup_a = ta_short >= TOP_ACC_SHORT_MIN and ga_short >= GLOBAL_ACC_SHORT_MIN and tp_long >= TOP_POS_LONG_MIN
                    setup_b = ta_long >= TOP_ACC_LONG_MIN and ga_long >= GLOBAL_ACC_LONG_MIN and tp_short >= TOP_POS_SHORT_MIN
                    
                    if not (setup_a or setup_b):
                        return
                    
                    passed_traders += 1
                    
                    # ---- SECOND: Get OI for symbols that passed traders filter
                    oi = await latest_async(session, "/futures/data/openInterestHist", sym, PERIOD)
                    if not oi:
                        return
                    oi_usdt = f(oi.get("sumOpenInterestValue"))
                    if oi_usdt is None or oi_usdt < MIN_OI_USDT:
                        return
                    
                    # ---- THIRD: Get funding rate and current price (single API call)
                    funding_rate, current_price = await get_premium_data_async(session, sym)
                    
                    # ---- FOURTH: Get volume data (24h and 2h candle)
                    volume_24h, volume_2h = await get_volume_data_async(session, sym)

                    # Queue inserts (one or two depending on setups)
                    if setup_a:
                        await insert_queue.put((
                            run_id, sym, "CROWD_SHORT__TOP_LONG", ts_ms, oi_usdt,
                            ta_long, ta_short, ga_long, ga_short, tp_long, tp_short,
                            funding_rate, current_price, volume_24h, volume_2h
                        ))

                    if setup_b:
                        await insert_queue.put((
                            run_id, sym, "CROWD_LONG__TOP_SHORT", ts_ms, oi_usdt,
                            ta_long, ta_short, ga_long, ga_short, tp_long, tp_short,
                            funding_rate, current_price, volume_24h, volume_2h
                        ))
                
                except Exception as e:
                    print(f"Error on {sym}: {e}")
                
                await asyncio.sleep(SLEEP_S)
        
        # Database writer task (processes queue)
        async def db_writer():
            nonlocal inserted
            while True:
                try:
                    row_data = await asyncio.wait_for(insert_queue.get(), timeout=1.0)
                    con.execute(sql, row_data)
                    con.commit()
                    inserted += 1
                except asyncio.TimeoutError:
                    # Check if all symbols have been processed
                    if scanned >= total_symbols:
                        break
        
        # Run symbol processing and DB writer concurrently
        await asyncio.gather(
            db_writer(),
            asyncio.gather(*[process_symbol(sym) for sym in symbols])
        )
    
    print(f"Done. scanned={scanned}/{total_symbols} | traders_pass={passed_traders} | rows={inserted}")
    return inserted


def export_to_csv(con: sqlite3.Connection, run_id: int):
    """
    Export results to CSV with:
    - Highlighted rows where funding confirms crowd position
    - Sorted by OI within each section
    """
    
    # Query for SHORT signals
    short_signals = con.execute("""
        SELECT 
            symbol, setup, oi_usdt,
            top_acc_long, top_acc_short,
            glob_acc_long, glob_acc_short,
            top_pos_long, top_pos_short,
            funding_rate, current_price, volume_24h, volume_2h
        FROM scan_hits
        WHERE run_id = ? AND setup = 'CROWD_SHORT__TOP_LONG'
        ORDER BY oi_usdt DESC
    """, (run_id,)).fetchall()
    
    # Query for LONG signals
    long_signals = con.execute("""
        SELECT 
            symbol, setup, oi_usdt,
            top_acc_long, top_acc_short,
            glob_acc_long, glob_acc_short,
            top_pos_long, top_pos_short,
            funding_rate, current_price, volume_24h, volume_2h
        FROM scan_hits
        WHERE run_id = ? AND setup = 'CROWD_LONG__TOP_SHORT'
        ORDER BY oi_usdt DESC
    """, (run_id,)).fetchall()
    
    def should_highlight(setup: str, funding_rate: Optional[float]) -> bool:
        """Check if funding confirms crowd position"""
        if funding_rate is None:
            return False
        # For CROWD_SHORT setup: negative funding confirms (shorts paying)
        if setup == "CROWD_SHORT__TOP_LONG" and funding_rate < -FUNDING_CONFIRM_THRESHOLD:
            return True
        # For CROWD_LONG setup: positive funding confirms (longs paying)
        if setup == "CROWD_LONG__TOP_SHORT" and funding_rate > FUNDING_CONFIRM_THRESHOLD:
            return True
        return False
    
    def format_row(row, highlight=False):
        """Format a data row with optional highlight marker"""
        marker = "⭐ " if highlight else ""
        return [
            marker + row[0],  # symbol with marker
            row[1],  # setup
            f"{row[2]:,.0f}",  # OI
            f"{row[3]*100:.1f}",  # top_acc_long
            f"{row[4]*100:.1f}",  # top_acc_short
            f"{row[5]*100:.1f}",  # glob_acc_long
            f"{row[6]*100:.1f}",  # glob_acc_short
            f"{row[7]*100:.1f}",  # top_pos_long
            f"{row[8]*100:.1f}",  # top_pos_short
            f"{row[9]*100:.4f}%" if row[9] is not None else "N/A",  # funding_rate
            f"${row[10]:,.2f}" if row[10] is not None else "N/A",  # current_price
            f"{row[11]:,.0f}" if row[11] is not None else "N/A",  # volume_24h
            f"{row[12]:,.0f}" if row[12] is not None else "N/A",  # volume_2h
        ]
    
    # Categorize signals
    short_highlighted = [r for r in short_signals if should_highlight(r[1], r[9])]
    short_regular = [r for r in short_signals if not should_highlight(r[1], r[9])]
    
    long_highlighted = [r for r in long_signals if should_highlight(r[1], r[9])]
    long_regular = [r for r in long_signals if not should_highlight(r[1], r[9])]
    
    # Write to CSV
    with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        
        # Header
        writer.writerow([
            'Symbol', 'Setup', 'OI (USDT)', 
            'Top Acc Long %', 'Top Acc Short %',
            'Global Acc Long %', 'Global Acc Short %',
            'Top Pos Long %', 'Top Pos Short %',
            'Funding Rate', 'Current Price', 'Volume 24h', 'Volume 2h'
        ])
        
        # ===== CROWD SHORT SECTION =====
        if short_signals:
            writer.writerow([])
            writer.writerow(['═══════════════════════════════════════════════════'])
            writer.writerow(['===  CROWD SHORT / TOP TRADERS LONG  ==='])
            writer.writerow(['═══════════════════════════════════════════════════'])
            writer.writerow([])
            
            # Highlighted (funding confirms)
            if short_highlighted:
                writer.writerow(['⭐ FUNDING CONFIRMS CROWD SHORT (Highlighted) ⭐'])
                writer.writerow([])
                for row in short_highlighted:
                    writer.writerow(format_row(row, highlight=True))
                writer.writerow([])
            
            # Regular signals
            if short_regular:
                if short_highlighted:
                    writer.writerow(['--- Other Signals ---'])
                    writer.writerow([])
                for row in short_regular:
                    writer.writerow(format_row(row))
        
        # ===== CROWD LONG SECTION =====
        if long_signals:
            writer.writerow([])
            writer.writerow([])
            writer.writerow(['═══════════════════════════════════════════════════'])
            writer.writerow(['===  CROWD LONG / TOP TRADERS SHORT  ==='])
            writer.writerow(['═══════════════════════════════════════════════════'])
            writer.writerow([])
            
            # Highlighted (funding confirms)
            if long_highlighted:
                writer.writerow(['⭐ FUNDING CONFIRMS CROWD LONG (Highlighted) ⭐'])
                writer.writerow([])
                for row in long_highlighted:
                    writer.writerow(format_row(row, highlight=True))
                writer.writerow([])
            
            # Regular signals
            if long_regular:
                if long_highlighted:
                    writer.writerow(['--- Other Signals ---'])
                    writer.writerow([])
                for row in long_regular:
                    writer.writerow(format_row(row))
    
    # Summary
    total_signals = len(short_signals) + len(long_signals)
    total_highlighted = len(short_highlighted) + len(long_highlighted)
    
    print(f"\n✅ CSV exported to: {CSV_PATH}")
    print(f"   - Crowd SHORT signals: {len(short_signals)} ({len(short_highlighted)} highlighted)")
    print(f"   - Crowd LONG signals: {len(long_signals)} ({len(long_highlighted)} highlighted)")
    print(f"   - ⭐ Funding confirmed: {total_highlighted}")
    print(f"   - Total signals: {total_signals}")


def main():
    con = sqlite3.connect(DB_PATH)
    try:
        init_db(con)
        reset_db(con)
        run_id = create_run(con)

        symbols = list_usdt_perp_symbols()
        print(f"Total USDT perpetual symbols found: {len(symbols)}")

        inserted_rows = scan_and_store(con, run_id, symbols)

        print(f"\nRows written to DB: {inserted_rows}")
        print(f"Database file: {DB_PATH}")
        
        # Export to CSV automatically
        if inserted_rows > 0:
            export_to_csv(con, run_id)
        else:
            print(f"\n⚠️  No signals found - CSV not created")

    finally:
        con.close()


if __name__ == "__main__":
    main()
