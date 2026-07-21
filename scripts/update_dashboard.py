"""
BITCLUB Research - 빗썸 단독 상장 코인 대시보드
=================================================

기능:
1. 5개 거래소 API에서 상장 종목 조회
2. CoinGecko API로 티커 충돌 검증
3. 이전 실행 결과와 비교하여 변동사항 감지
4. HTML 대시보드 자동 생성 (site/index.html)
5. 변동사항 로그 및 CSV 아카이브

GitHub Actions에서 매시간 자동 실행됨.
"""

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

import requests

# ---------- 설정 ----------
KST = timezone(timedelta(hours=9))

# API 엔드포인트
BITHUMB_URL = "https://api.bithumb.com/public/ticker/ALL_KRW"
UPBIT_URL = "https://api.upbit.com/v1/market/all"
BINANCE_SPOT_URL = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_FUTURES_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
COINBASE_URL = "https://api.exchange.coinbase.com/products"
KRAKEN_URL = "https://api.kraken.com/0/public/AssetPairs"

# CoinGecko API (무료 티어)
COINGECKO_LIST_URL = "https://api.coingecko.com/api/v3/coins/list"

# 티커 충돌 의심 목록 (자동 검출 + 수동 추가)
SUSPICIOUS_TICKERS = {"AI", "S", "C", "D", "H", "BB", "UP"}

# 경로
SITE_DIR = "site"
DATA_DIR = "data"
LOG_FILE = os.path.join(DATA_DIR, "changes_log.json")
LATEST_CSV = os.path.join(DATA_DIR, "latest.csv")

REQUEST_TIMEOUT = 15


# ===================== API 호출 =====================

def fetch_bithumb():
    res = requests.get(BITHUMB_URL, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    data = res.json().get("data", {})
    return {t.upper() for t in data.keys() if t != "date"}


def fetch_upbit():
    res = requests.get(UPBIT_URL, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    return {item["market"].split("-")[1].upper() for item in res.json()}


def fetch_binance_spot():
    res = requests.get(BINANCE_SPOT_URL, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    return {
        s["baseAsset"].upper()
        for s in res.json().get("symbols", [])
        if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
    }


def fetch_binance_futures():
    res = requests.get(BINANCE_FUTURES_URL, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    return {
        s["baseAsset"].upper()
        for s in res.json().get("symbols", [])
        if s.get("contractType") == "PERPETUAL"
        and s.get("quoteAsset") == "USDT"
        and s.get("status") == "TRADING"
    }


def fetch_coinbase():
    res = requests.get(COINBASE_URL, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    return {
        p["base_currency"].upper()
        for p in res.json()
        if p.get("quote_currency") in ("USD", "USDC")
        and p.get("status") == "online"
        and not p.get("trading_disabled", False)
    }


def fetch_kraken():
    res = requests.get(KRAKEN_URL, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    pairs = res.json().get("result", {})
    result = set()
    for info in pairs.values():
        quote = info.get("quote", "")
        if quote not in ("ZUSD", "USD", "USDT"):
            continue
        base = info.get("base", "").upper()
        if len(base) == 4 and base.startswith("X"):
            base = base[1:]
        if base == "XBT":
            base = "BTC"
        result.add(base)
    return result


def fetch_coingecko_map():
    """
    CoinGecko 전체 코인 리스트 조회.
    { symbol_upper: [ {id, name}, ... ] } 형태로 반환.
    같은 심볼에 여러 프로젝트가 있으면 리스트로 저장.
    """
    try:
        res = requests.get(COINGECKO_LIST_URL, timeout=REQUEST_TIMEOUT)
        res.raise_for_status()
        coins = res.json()
        symbol_map = {}
        for c in coins:
            symbol = c.get("symbol", "").upper()
            if not symbol:
                continue
            symbol_map.setdefault(symbol, []).append({
                "id": c.get("id"),
                "name": c.get("name"),
            })
        return symbol_map
    except Exception as e:
        print(f"  [경고] CoinGecko 조회 실패: {e}", file=sys.stderr)
        return {}


# ===================== 변동 추적 =====================

def load_previous():
    """이전 실행 결과 로드."""
    if not os.path.exists(LATEST_CSV):
        return None
    tickers = set()
    with open(LATEST_CSV, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            tickers.add(row["ticker"])
    return tickers


def load_change_log():
    """변동 로그 로드."""
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_change_log(log_entries):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log_entries, f, ensure_ascii=False, indent=2)


# ===================== HTML 생성 =====================

def render_mark(is_yes):
    if is_yes:
        return '<span class="mark yes">●</span>'
    return '<span class="mark no">·</span>'


def render_row(coin, is_new=False):
    ticker_class = "ticker warning" if coin["ticker"] in SUSPICIOUS_TICKERS else "ticker"
    new_badge = '<span class="badge-new">NEW</span>' if is_new else ""
    return f"""
        <tr data-ticker="{coin['ticker']}"
            data-bn-spot="{'1' if coin['bn_spot'] else '0'}"
            data-bn-fut="{'1' if coin['bn_fut'] else '0'}"
            data-cb="{'1' if coin['cb'] else '0'}"
            data-kr="{'1' if coin['kr'] else '0'}"
            data-new="{'1' if is_new else '0'}"
            data-count="{coin['count']}">
            <td><span class="{ticker_class}">{coin['ticker']}</span>{new_badge}</td>
            <td>{render_mark(coin['bn_spot'])}</td>
            <td>{render_mark(coin['bn_fut'])}</td>
            <td>{render_mark(coin['cb'])}</td>
            <td>{render_mark(coin['kr'])}</td>
        </tr>
    """


def generate_html(coins, stats, changes, updated_at):
    """대시보드 HTML 생성."""
    # 코인 정렬 (신규 진입 종목 우선, 그 다음 알파벳 순)
    added_set = set(changes.get("added", []))
    sorted_coins = sorted(coins, key=lambda c: (c["ticker"] not in added_set, c["ticker"]))

    rows_html = "\n".join(render_row(c, is_new=c["ticker"] in added_set) for c in sorted_coins)

    # 변동 배너 문구
    if changes.get("first_run"):
        banner_message = "첫 실행 · 다음 갱신부터 변동사항이 표시됩니다"
        banner_visible = False
    elif not changes["added"] and not changes["removed"]:
        banner_message = "이전 갱신 대비 변동 없음"
        banner_visible = True
    else:
        parts = []
        if changes["added"]:
            parts.append(f'<span class="added">+{len(changes["added"])} 신규 진입</span> ({", ".join(changes["added"])})')
        if changes["removed"]:
            parts.append(f'<span class="removed">-{len(changes["removed"])} 이탈</span> ({", ".join(changes["removed"])})')
        banner_message = " · ".join(parts)
        banner_visible = True

    # 통계 카드
    total = stats["total"]
    bn_fut_cnt = stats["bn_fut"]
    all4 = stats["all4"]
    suspicious_cnt = stats["suspicious"]

    prev_total = stats.get("prev_total")
    if prev_total is not None:
        diff = total - prev_total
        total_change = (
            f'<div class="change up">+{diff} vs 직전</div>' if diff > 0
            else f'<div class="change down">{diff} vs 직전</div>' if diff < 0
            else '<div class="change">변동 없음</div>'
        )
    else:
        total_change = '<div class="change">첫 측정</div>'

    html = HTML_TEMPLATE.format(
        updated_at=updated_at,
        banner_display="flex" if banner_visible else "none",
        banner_message=banner_message,
        total=total,
        total_change=total_change,
        bn_fut=bn_fut_cnt,
        all4=all4,
        suspicious=suspicious_cnt,
        rows=rows_html,
        filter_all=total,
        filter_bn_fut=bn_fut_cnt,
        filter_all4=all4,
        filter_new=len(changes.get("added", [])),
        year=datetime.now(KST).year,
    )

    os.makedirs(SITE_DIR, exist_ok=True)
    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BITCLUB Research · 빗썸 단독 상장 코인 대시보드</title>
<meta name="description" content="빗썸에만 상장되고 업비트엔 없는 코인들의 해외 거래소 상장 현황. 매시간 자동 갱신.">
<style>
:root {{
    --bg: #f8fafc;
    --bg-card: #ffffff;
    --bg-hover: #f1f5f9;
    --bg-subtle: #f8fafc;
    --border: #e2e8f0;
    --border-strong: #cbd5e1;
    --text: #0f172a;
    --text-muted: #64748b;
    --text-dim: #94a3b8;
    --accent: #2563eb;
    --accent-hover: #1d4ed8;
    --accent-bg: #eff6ff;
    --success: #059669;
    --success-bg: #ecfdf5;
    --warning: #d97706;
    --warning-bg: #fffbeb;
    --danger: #dc2626;
    --danger-bg: #fef2f2;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Noto Sans KR', 'Segoe UI', sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.6; min-height: 100vh; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 32px 24px; }}
.header {{ display: flex; justify-content: space-between; align-items: flex-start;
    padding-bottom: 24px; border-bottom: 2px solid var(--text); margin-bottom: 32px;
    flex-wrap: wrap; gap: 16px; }}
.brand {{ font-size: 11px; font-weight: 700; color: var(--accent); letter-spacing: 2px; margin-bottom: 6px; }}
h1 {{ font-size: 28px; font-weight: 700; margin-bottom: 8px; letter-spacing: -0.5px; }}
.subtitle {{ color: var(--text-muted); font-size: 14px; }}
.last-updated {{ text-align: right; font-size: 12px; color: var(--text-dim); }}
.last-updated .value {{ color: var(--success); font-weight: 600; font-size: 14px;
    margin-top: 4px; display: flex; align-items: center; gap: 6px; justify-content: flex-end; }}
.pulse {{ display: inline-block; width: 8px; height: 8px; background: var(--success);
    border-radius: 50%; animation: pulse 2s infinite; }}
@keyframes pulse {{
    0% {{ opacity: 1; transform: scale(1); }}
    50% {{ opacity: 0.4; transform: scale(1.2); }}
    100% {{ opacity: 1; transform: scale(1); }}
}}
.alert-banner {{ background: var(--accent-bg); border: 1px solid #bfdbfe;
    border-left: 4px solid var(--accent); border-radius: 8px; padding: 18px 22px;
    margin-bottom: 32px; display: {banner_display}; align-items: center; gap: 16px; flex-wrap: wrap; }}
.alert-banner .icon {{ font-size: 24px; }}
.alert-banner .content {{ flex: 1; min-width: 260px; }}
.alert-banner .title {{ font-size: 13px; color: var(--accent); font-weight: 700;
    margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px; }}
.alert-banner .message {{ font-size: 15px; color: var(--text); }}
.alert-banner .added {{ color: var(--success); font-weight: 700; }}
.alert-banner .removed {{ color: var(--danger); font-weight: 700; }}
.stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 14px; margin-bottom: 32px; }}
.stat-card {{ background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 10px; padding: 20px; transition: all 0.15s; }}
.stat-card:hover {{ border-color: var(--accent); box-shadow: 0 2px 8px rgba(37, 99, 235, 0.08); }}
.stat-card .label {{ font-size: 11px; color: var(--text-muted); margin-bottom: 10px;
    text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; }}
.stat-card .value {{ font-size: 34px; font-weight: 700; line-height: 1; margin-bottom: 6px; }}
.stat-card.accent .value {{ color: var(--success); }}
.stat-card.warn .value {{ color: var(--warning); }}
.stat-card .change {{ font-size: 12px; color: var(--text-dim); }}
.stat-card .change.up {{ color: var(--success); font-weight: 600; }}
.stat-card .change.down {{ color: var(--danger); font-weight: 600; }}
.filters {{ background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 10px; padding: 18px 22px; margin-bottom: 20px; }}
.filters-title {{ font-size: 11px; color: var(--text-muted); margin-bottom: 12px;
    text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; }}
.filter-chips {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.chip {{ background: var(--bg-card); border: 1px solid var(--border-strong);
    color: var(--text-muted); padding: 7px 14px; border-radius: 20px; font-size: 13px;
    cursor: pointer; transition: all 0.15s; user-select: none; font-weight: 500; }}
.chip:hover {{ color: var(--text); border-color: var(--accent); background: var(--accent-bg); }}
.chip.active {{ background: var(--text); color: white; border-color: var(--text); }}
.search-box {{ margin-top: 14px; position: relative; }}
.search-box input {{ width: 100%; background: var(--bg-subtle); border: 1px solid var(--border);
    color: var(--text); padding: 10px 14px 10px 40px; border-radius: 8px; font-size: 14px;
    outline: none; transition: all 0.15s; font-family: inherit; }}
.search-box input:focus {{ border-color: var(--accent); background: white;
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1); }}
.search-box::before {{ content: "🔍"; position: absolute; left: 14px; top: 50%;
    transform: translateY(-50%); font-size: 14px; opacity: 0.5; }}
.table-wrapper {{ background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 10px; overflow: hidden; margin-bottom: 32px; }}
.table-header {{ padding: 18px 22px; border-bottom: 1px solid var(--border);
    display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }}
.table-title {{ font-size: 15px; font-weight: 700; }}
.count-badge {{ background: var(--accent-bg); color: var(--accent); padding: 3px 10px;
    border-radius: 12px; font-size: 12px; margin-left: 8px; font-weight: 600; }}
table {{ width: 100%; border-collapse: collapse; }}
th {{ background: var(--bg-subtle); color: var(--text-muted); font-weight: 700;
    text-align: center; padding: 12px 8px; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.5px; border-bottom: 1px solid var(--border); }}
th:first-child {{ text-align: left; padding-left: 22px; }}
td {{ padding: 12px 8px; border-bottom: 1px solid var(--border); font-size: 14px; text-align: center; }}
td:first-child {{ text-align: left; padding-left: 22px; }}
tr:hover td {{ background: var(--bg-subtle); }}
tr:last-child td {{ border-bottom: none; }}
tr.hidden {{ display: none; }}
.ticker {{ font-family: 'SF Mono', Monaco, Consolas, monospace; font-weight: 700;
    color: var(--text); letter-spacing: 0.3px; }}
.ticker.warning::after {{ content: " ⚠️"; font-size: 11px; }}
.mark {{ font-size: 16px; line-height: 22px; display: inline-block; width: 22px;
    height: 22px; border-radius: 50%; text-align: center; }}
.mark.yes {{ color: var(--success); background: var(--success-bg); }}
.mark.no {{ color: var(--text-dim); opacity: 0.3; }}
.badge-new {{ background: var(--success); color: white; font-size: 10px; font-weight: 700;
    padding: 2px 8px; border-radius: 4px; margin-left: 6px; text-transform: uppercase; letter-spacing: 0.5px; }}
.newsletter {{ background: linear-gradient(135deg, var(--accent-bg), #f0f9ff);
    border: 1px solid #bfdbfe; border-radius: 12px; padding: 32px 24px;
    margin-bottom: 32px; text-align: center; }}
.newsletter h2 {{ font-size: 22px; margin-bottom: 8px; }}
.newsletter p {{ color: var(--text-muted); margin-bottom: 20px; font-size: 14px;
    max-width: 500px; margin-left: auto; margin-right: auto; }}
.newsletter-form {{ display: flex; gap: 8px; max-width: 440px; margin: 0 auto; flex-wrap: wrap; }}
.newsletter-form input {{ flex: 1; min-width: 200px; background: white;
    border: 1px solid var(--border-strong); color: var(--text); padding: 12px 16px;
    border-radius: 8px; font-size: 14px; outline: none; transition: all 0.15s; font-family: inherit; }}
.newsletter-form input:focus {{ border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1); }}
.newsletter-form button {{ background: var(--text); color: white; border: none;
    padding: 12px 24px; border-radius: 8px; font-size: 14px; font-weight: 600;
    cursor: pointer; transition: all 0.15s; font-family: inherit; }}
.newsletter-form button:hover {{ background: var(--accent); transform: translateY(-1px); }}
.footer {{ text-align: center; color: var(--text-dim); font-size: 12px;
    padding-top: 24px; border-top: 1px solid var(--border); }}
.footer a {{ color: var(--text-muted); text-decoration: none; font-weight: 500; }}
.footer a:hover {{ color: var(--accent); }}
.footer .disclaimer {{ margin-top: 12px; font-size: 11px; opacity: 0.7; }}
@media (max-width: 640px) {{
    .container {{ padding: 20px 16px; }}
    h1 {{ font-size: 22px; }}
    .stat-card .value {{ font-size: 26px; }}
    table {{ font-size: 12px; }}
    th, td {{ padding: 10px 6px; }}
    th:first-child, td:first-child {{ padding-left: 16px; }}
}}
</style>
</head>
<body>
<div class="container">

<div class="header">
    <div>
        <div class="brand">BITCLUB · COIN RESEARCH</div>
        <h1>빗썸 단독 상장 코인 대시보드</h1>
        <div class="subtitle">차트로 검증하는 리서치 · 매시간 자동 갱신</div>
    </div>
    <div class="last-updated">
        마지막 갱신
        <div class="value"><span class="pulse"></span>{updated_at}</div>
    </div>
</div>

<div class="alert-banner">
    <div class="icon">🔔</div>
    <div class="content">
        <div class="title">지난 갱신 대비 변동사항</div>
        <div class="message">{banner_message}</div>
    </div>
</div>

<div class="stats-grid">
    <div class="stat-card">
        <div class="label">최종 후보</div>
        <div class="value">{total}</div>
        {total_change}
    </div>
    <div class="stat-card accent">
        <div class="label">바이낸스 선물</div>
        <div class="value">{bn_fut}</div>
        <div class="change">펀딩비 캡처 가능</div>
    </div>
    <div class="stat-card">
        <div class="label">4개 거래소 모두</div>
        <div class="value">{all4}</div>
        <div class="change">유동성 최상위</div>
    </div>
    <div class="stat-card warn">
        <div class="label">티커 검증 필요</div>
        <div class="value">{suspicious}</div>
        <div class="change">충돌 의심 종목</div>
    </div>
</div>

<div class="filters">
    <div class="filters-title">필터</div>
    <div class="filter-chips">
        <span class="chip active" data-filter="all">전체 ({filter_all})</span>
        <span class="chip" data-filter="bn-fut">바이낸스 선물만 ({filter_bn_fut})</span>
        <span class="chip" data-filter="all4">4개 거래소 모두 ({filter_all4})</span>
        <span class="chip" data-filter="new">신규 진입 ({filter_new})</span>
    </div>
    <div class="search-box">
        <input type="text" id="search" placeholder="티커 검색... (예: BNB, POPCAT)">
    </div>
</div>

<div class="table-wrapper">
    <div class="table-header">
        <div>
            <span class="table-title">전체 종목 현황</span>
            <span class="count-badge" id="count-badge">{total}종</span>
        </div>
    </div>
    <table>
        <thead>
            <tr>
                <th>티커</th>
                <th>BN 현물</th>
                <th>BN 선물</th>
                <th>코인베이스</th>
                <th>크라켄</th>
            </tr>
        </thead>
        <tbody id="tbody">
            {rows}
        </tbody>
    </table>
</div>

<div class="newsletter">
    <h2>📬 변동사항 이메일 알림</h2>
    <p>신규 상장이나 업비트 진입 등 리스트 변동이 발생하면 이메일로 알려드립니다. 무료 · 언제든 구독 취소.</p>
    <div class="newsletter-form">
        <input type="email" placeholder="이메일 주소 (준비 중)" disabled>
        <button disabled>구독하기</button>
    </div>
</div>

<div class="footer">
    <div>© {year} BITCLUB Research · 차트스트레이트</div>
    <div class="disclaimer">
        본 자료는 정보 제공 목적이며 투자 조언이 아닙니다.<br>
        데이터: Bithumb, Upbit, Binance, Coinbase, Kraken, CoinGecko Public API
    </div>
</div>

</div>

<script>
// 필터링 및 검색 로직
const chips = document.querySelectorAll('.chip');
const search = document.getElementById('search');
const tbody = document.getElementById('tbody');
const countBadge = document.getElementById('count-badge');
let currentFilter = 'all';

function applyFilters() {{
    const searchTerm = search.value.toUpperCase();
    const rows = tbody.querySelectorAll('tr');
    let visibleCount = 0;

    rows.forEach(row => {{
        const ticker = row.dataset.ticker || '';
        const bnFut = row.dataset.bnFut === '1';
        const count = parseInt(row.dataset.count || '0');
        const isNew = row.dataset.new === '1';

        let filterMatch = true;
        if (currentFilter === 'bn-fut') filterMatch = bnFut;
        else if (currentFilter === 'all4') filterMatch = count === 4;
        else if (currentFilter === 'new') filterMatch = isNew;

        const searchMatch = !searchTerm || ticker.includes(searchTerm);

        if (filterMatch && searchMatch) {{
            row.classList.remove('hidden');
            visibleCount++;
        }} else {{
            row.classList.add('hidden');
        }}
    }});

    countBadge.textContent = visibleCount + '종';
}}

chips.forEach(chip => {{
    chip.addEventListener('click', () => {{
        chips.forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        currentFilter = chip.dataset.filter;
        applyFilters();
    }});
}});

search.addEventListener('input', applyFilters);
</script>

</body>
</html>
"""


# ===================== 메인 =====================

def main():
    now = datetime.now(KST)
    updated_at = now.strftime("%Y-%m-%d %H:%M KST")
    date_str = now.strftime("%Y-%m-%d %H:%M")

    print("=" * 70)
    print(f"BITCLUB Research 대시보드 갱신 · {updated_at}")
    print("=" * 70)

    # 1. 데이터 수집
    print("\n[1/3] 거래소 API 조회 중...")
    bithumb = fetch_bithumb();       print(f"  빗썸: {len(bithumb)}종")
    upbit = fetch_upbit();           print(f"  업비트: {len(upbit)}종")
    bn_spot = fetch_binance_spot();  print(f"  바이낸스 현물: {len(bn_spot)}종")
    bn_fut = fetch_binance_futures();print(f"  바이낸스 선물: {len(bn_fut)}종")
    cb = fetch_coinbase();           print(f"  코인베이스: {len(cb)}종")
    kr = fetch_kraken();             print(f"  크라켄: {len(kr)}종")

    # 필터링
    bithumb_only = bithumb - upbit
    any_foreign = bn_spot | bn_fut | cb | kr
    candidates_set = bithumb_only & any_foreign

    coins = []
    for t in sorted(candidates_set):
        c = {
            "ticker": t,
            "bn_spot": t in bn_spot,
            "bn_fut": t in bn_fut,
            "cb": t in cb,
            "kr": t in kr,
        }
        c["count"] = sum([c["bn_spot"], c["bn_fut"], c["cb"], c["kr"]])
        coins.append(c)

    total = len(coins)
    print(f"\n  최종 후보: {total}종")

    # 2. 변동 감지
    print("\n[2/3] 변동사항 감지 중...")
    prev_tickers = load_previous()
    current_tickers = {c["ticker"] for c in coins}

    if prev_tickers is None:
        changes = {"first_run": True, "added": [], "removed": []}
        print("  첫 실행 · 다음 갱신부터 비교 시작")
    else:
        added = sorted(current_tickers - prev_tickers)
        removed = sorted(prev_tickers - current_tickers)
        changes = {"first_run": False, "added": added, "removed": removed}
        print(f"  신규 진입: {len(added)}종 {added if added else ''}")
        print(f"  이탈: {len(removed)}종 {removed if removed else ''}")

    # 3. HTML 생성 및 저장
    print("\n[3/3] HTML 생성 및 저장...")
    os.makedirs(DATA_DIR, exist_ok=True)

    stats = {
        "total": total,
        "bn_fut": sum(1 for c in coins if c["bn_fut"]),
        "all4": sum(1 for c in coins if c["count"] == 4),
        "suspicious": sum(1 for c in coins if c["ticker"] in SUSPICIOUS_TICKERS),
        "prev_total": len(prev_tickers) if prev_tickers else None,
    }

    generate_html(coins, stats, changes, updated_at)
    print(f"  site/index.html 생성 완료")

    # CSV 저장 (다음 실행 비교용)
    with open(LATEST_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["ticker", "bn_spot", "bn_fut", "cb", "kr"])
        writer.writeheader()
        for c in coins:
            writer.writerow({
                "ticker": c["ticker"],
                "bn_spot": "Y" if c["bn_spot"] else "N",
                "bn_fut": "Y" if c["bn_fut"] else "N",
                "cb": "Y" if c["cb"] else "N",
                "kr": "Y" if c["kr"] else "N",
            })
    print(f"  {LATEST_CSV} 저장 완료")

    # 변동 로그 (변동사항 있을 때만 기록)
    if not changes["first_run"] and (changes["added"] or changes["removed"]):
        log = load_change_log()
        log.insert(0, {
            "timestamp": date_str,
            "added": changes["added"],
            "removed": changes["removed"],
            "total": total,
        })
        log = log[:100]  # 최대 100개 유지
        save_change_log(log)
        print(f"  {LOG_FILE} 변동 로그 추가")

    print("\n완료.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
