# -*- coding: utf-8 -*-
"""
分析師追蹤系統 — 行情儀表板後端
  啟動: python app.py  ->  http://127.0.0.1:5177
資料源 (皆為官方公開資料):
  - 證交所 TWSE rwd API: 加權指數/個股日K、三大法人、個股法人買賣超排行
  - 櫃買中心 TPEX openapi: 櫃買指數日K、上櫃法人
  - 證交所 MIS: 即時報價 (加權/櫃買指數、個股)
  - 期交所 TAIFEX: 小台/微台 全市場與三大法人未平倉 -> 散戶多空比
  - 集保 TDCC opendata: 股權分散表 (大戶/散戶持股張數)
"""
import os, io, re, csv, json, time, threading
from datetime import date, datetime, timedelta

import requests
from flask import Flask, jsonify, request, send_from_directory

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)
REC_PATH = os.path.join(os.path.dirname(BASE), "recommendations.json")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

app = Flask(__name__, static_folder="static", static_url_path="")


# ---------------- 快取 ----------------

def cache_get(key, ttl_sec):
    """ttl_sec=None 表示永久快取"""
    path = os.path.join(CACHE_DIR, key + ".json")
    if not os.path.exists(path):
        return None
    if ttl_sec is not None and time.time() - os.path.getmtime(path) > ttl_sec:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def cache_set(key, obj):
    with open(os.path.join(CACHE_DIR, key + ".json"), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def num(s):
    """'10,591.62' -> float; 無法解析回傳 None"""
    try:
        return float(str(s).replace(",", ""))
    except (ValueError, TypeError):
        return None


def roc_to_iso(s):
    """'115/07/01' -> '2026-07-01'"""
    y, m, d = s.strip().split("/")
    return f"{int(y) + 1911}-{m}-{d}"


def month_starts(months):
    """最近 N 個月的每月1日 (含本月), 由舊到新"""
    today = date.today()
    out = []
    y, m = today.year, today.month
    for _ in range(months):
        out.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def is_past_month(d):
    t = date.today()
    return (d.year, d.month) < (t.year, t.month)


# ---------------- 指數/個股 日K ----------------

def twse_month_kline(url_tmpl, key_prefix, d):
    """抓 TWSE 單月資料, 過去月份永久快取, 本月快取10分鐘"""
    key = f"{key_prefix}_{d:%Y%m}"
    ttl = None if is_past_month(d) else 600
    cached = cache_get(key, ttl)
    if cached is not None:
        return cached
    r = requests.get(url_tmpl.format(date=f"{d:%Y%m%d}"), headers=UA, timeout=20)
    rows = r.json().get("data") or []
    cache_set(key, rows)
    return rows


@app.route("/api/index_kline")
def index_kline():
    market = request.args.get("market", "tse")
    months = min(int(request.args.get("months", 6)), 24)
    out = []
    if market == "tse":
        for d in month_starts(months):
            rows = twse_month_kline(
                "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date={date}&response=json",
                "taiex", d)
            for row in rows:  # [日期, 開, 高, 低, 收]
                o, h, l, c = num(row[1]), num(row[2]), num(row[3]), num(row[4])
                if None in (o, h, l, c):
                    continue
                out.append({"time": roc_to_iso(row[0]), "open": o, "high": h, "low": l, "close": c})
    else:  # otc: Yahoo Finance ^TWOII 補歷史 + 櫃買 openapi 本月資料
        key = "tpex_index_hist"
        hist = cache_get(key, 600) or cache_get(key, None) or {}
        try:
            r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/%5ETWOII",
                             params={"range": f"{months}mo", "interval": "1d"},
                             headers=UA, timeout=20)
            res = r.json()["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            for i, ts in enumerate(res["timestamp"]):
                o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
                if None in (o, h, l, c):
                    continue
                iso = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                hist[iso] = [round(o, 2), round(h, 2), round(l, 2), round(c, 2)]
        except Exception:
            pass
        # 櫃買 openapi 本月資料 (官方數字, 覆蓋 Yahoo)
        try:
            r = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_index", headers=UA, timeout=20)
            for row in r.json():
                dt = row["Date"]
                iso = f"{dt[:4]}-{dt[4:6]}-{dt[6:]}"
                o, h, l, c = num(row["Open"]), num(row["High"]), num(row["Low"]), num(row["Close"])
                if None in (o, h, l, c):
                    continue
                hist[iso] = [o, h, l, c]
        except Exception:
            pass
        cache_set(key, hist)
        cutoff = (date.today() - timedelta(days=months * 31)).isoformat()
        out = [{"time": k, "open": v[0], "high": v[1], "low": v[2], "close": v[3]}
               for k, v in sorted(hist.items()) if k >= cutoff]
    return jsonify(out)


@app.route("/api/stock_kline")
def stock_kline():
    code = re.sub(r"\W", "", request.args.get("code", ""))
    months = min(int(request.args.get("months", 6)), 24)
    if not code:
        return jsonify({"error": "缺少股票代號"}), 400
    out = []
    for d in month_starts(months):
        rows = twse_month_kline(
            "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={date}&stockNo=" + code + "&response=json",
            f"stk_{code}", d)
        for row in rows:  # [日期,成交股數,成交金額,開,高,低,收,漲跌,筆數]
            o, h, l, c = num(row[3]), num(row[4]), num(row[5]), num(row[6])
            if None in (o, h, l, c):
                continue
            vol = num(row[1])
            out.append({"time": roc_to_iso(row[0]), "open": o, "high": h, "low": l, "close": c,
                        "volume": (vol or 0) / 1000})
    if out:
        return jsonify(out)
    # 上櫃個股: 櫃買舊API
    for d in month_starts(months):
        key = f"otcstk_{code}_{d:%Y%m}"
        rows = cache_get(key, None if is_past_month(d) else 600)
        if rows is None:
            try:
                r = requests.get("https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php",
                                 params={"l": "zh-tw", "d": f"{d.year - 1911}/{d.month:02d}", "stkno": code},
                                 headers=UA, timeout=20)
                rows = r.json().get("aaData") or []
            except Exception:
                rows = []
            cache_set(key, rows)
        for row in rows:  # [日期,成交仟股,成交仟元,開,高,低,收,漲跌,筆數]
            o, h, l, c = num(row[3]), num(row[4]), num(row[5]), num(row[6])
            if None in (o, h, l, c):
                continue
            out.append({"time": roc_to_iso(row[0]), "open": o, "high": h, "low": l, "close": c,
                        "volume": num(row[1]) or 0})
    return jsonify(out)


# ---------------- 即時報價 ----------------

@app.route("/api/quote")
def quote():
    codes = request.args.get("codes", "")  # 例: t00,o00,2330 (t00=加權 o00=櫃買)
    exch = []
    for c in codes.split(","):
        c = c.strip()
        if not c:
            continue
        if c == "t00":
            exch.append("tse_t00.tw")
        elif c == "o00":
            exch.append("otc_o00.tw")
        else:
            exch.append(f"tse_{c}.tw")
            exch.append(f"otc_{c}.tw")
    r = requests.get("https://mis.twse.com.tw/stock/api/getStockInfo.jsp",
                     params={"ex_ch": "|".join(exch), "json": "1", "delay": "0"},
                     headers=UA, timeout=15)
    out = []
    for m in r.json().get("msgArray", []):
        if not m.get("z") and not m.get("y"):
            continue
        out.append({
            "code": m.get("c"), "name": m.get("n"), "market": m.get("ex"),
            "price": num(m.get("z")) or num(m.get("b", "").split("_")[0]),
            "prev_close": num(m.get("y")), "open": num(m.get("o")),
            "high": num(m.get("h")), "low": num(m.get("l")),
            "volume": num(m.get("v")), "time": m.get("t"),
        })
    return jsonify(out)


# ---------------- 三大法人 (整體, 近N日) ----------------

@app.route("/api/institutional")
def institutional():
    days = min(int(request.args.get("days", 30)), 90)
    out = []
    d = date.today()
    checked = 0
    while len(out) < days and checked < days * 2 + 10:
        key = f"bfi_{d:%Y%m%d}"
        ttl = None if d < date.today() else 600
        data = cache_get(key, ttl)
        if data is None:
            try:
                r = requests.get("https://www.twse.com.tw/rwd/zh/fund/BFI82U",
                                 params={"dayDate": f"{d:%Y%m%d}", "type": "day", "response": "json"},
                                 headers=UA, timeout=20)
                data = r.json().get("data") or []
            except Exception:
                data = []
            cache_set(key, data)
        if data:
            rec = {"date": d.isoformat(), "foreign": 0.0, "trust": 0.0, "dealer": 0.0}
            for row in data:  # [單位名稱, 買進金額, 賣出金額, 買賣差額]
                diff = (num(row[3]) or 0) / 1e8  # 億元
                if "外資" in row[0]:
                    rec["foreign"] += diff
                elif "投信" in row[0]:
                    rec["trust"] += diff
                elif "自營" in row[0]:
                    rec["dealer"] += diff
            out.append(rec)
        d -= timedelta(days=1)
        checked += 1
    return jsonify(list(reversed(out)))


# ---------------- 個股法人買賣超排行 ----------------

@app.route("/api/rankings")
def rankings():
    top = min(int(request.args.get("top", 10)), 50)
    d = date.today()
    data, used = None, None
    for _ in range(8):
        key = f"t86_{d:%Y%m%d}"
        ttl = None if d < date.today() else 600
        data = cache_get(key, ttl)
        if data is None:
            try:
                r = requests.get("https://www.twse.com.tw/rwd/zh/fund/T86",
                                 params={"date": f"{d:%Y%m%d}", "selectType": "ALLBUT0999", "response": "json"},
                                 headers=UA, timeout=30)
                data = r.json().get("data") or []
            except Exception:
                data = []
            cache_set(key, data)
        if data:
            used = d.isoformat()
            break
        d -= timedelta(days=1)
    if not data:
        return jsonify({"error": "近日無法人資料"}), 502
    stocks = []
    for row in data:  # [代號,名稱,外資買,外資賣,外資淨...(15)...三大法人淨(最後)]
        stocks.append({
            "code": row[0].strip(), "name": row[1].strip(),
            "foreign": (num(row[4]) or 0) / 1000,   # 千股->張
            "trust": (num(row[10]) or 0) / 1000,
            "total": (num(row[-1]) or 0) / 1000,
        })
    def ranked(field):
        s = sorted(stocks, key=lambda x: x[field])
        return {"buy": list(reversed(s[-top:])), "sell": s[:top]}
    return jsonify({"date": used, "foreign": ranked("foreign"),
                    "trust": ranked("trust"), "total": ranked("total")})


# ---------------- 散戶多空比 (小台/微台) ----------------

TAIFEX_NAMES = {"小型臺指期貨": "mtx", "微型臺指期貨": "tmf"}


def taifex_csv(url, params):
    r = requests.get(url, params=params, headers=UA, timeout=30)
    text = r.content.decode("big5", errors="ignore")
    return list(csv.reader(io.StringIO(text)))


@app.route("/api/retail_ratio")
def retail_ratio():
    days = min(int(request.args.get("days", 20)), 30)
    key = f"retail_{date.today():%Y%m%d}_{days}"
    cached = cache_get(key, 600)
    if cached is not None and (cached.get("mtx") or cached.get("tmf")):
        return jsonify(cached)
    start = date.today() - timedelta(days=28)
    end = date.today()
    # 三大法人未平倉: 此API不能跨月、且範圍含「尚無資料日」會整筆失敗 -> 按月查+回退結束日
    inst = {}  # (date, prod) -> [法人多方OI, 法人空方OI]
    month_ranges = []
    if start.month != end.month:
        last_prev = date(end.year, end.month, 1) - timedelta(days=1)
        month_ranges.append((start, last_prev, True))   # 上個月(完整): 永久快取
    month_ranges.append((date(end.year, end.month, 1), end, False))
    for s, e, permanent in month_ranges:
        ckey = f"taifex_inst_{s:%Y%m%d}_{e:%Y%m%d}"
        rows = cache_get(ckey, None if permanent else 600)
        if rows is None:
            rows = []
            e2 = e
            for _ in range(4):  # 結束日無資料則往前回退
                got = taifex_csv("https://www.taifex.com.tw/cht/3/futContractsDateDown",
                                 {"queryStartDate": f"{s:%Y/%m/%d}", "queryEndDate": f"{e2:%Y/%m/%d}"})
                if got and not got[0][0].startswith("<"):
                    rows = got
                    break
                e2 -= timedelta(days=1)
                if e2 < s:
                    break
            cache_set(ckey, rows)
        for row in rows[1:]:
            if len(row) < 13 or row[1].strip() not in TAIFEX_NAMES:
                continue
            k = (row[0].strip(), TAIFEX_NAMES[row[1].strip()])
            cur = inst.setdefault(k, [0, 0])
            cur[0] += num(row[9]) or 0
            cur[1] += num(row[11]) or 0
    # 全市場未平倉 (每日行情, 加總各到期月份; 此API可跨月)
    rng = {"queryStartDate": f"{start:%Y/%m/%d}", "queryEndDate": f"{end:%Y/%m/%d}"}
    total = {}  # (date, prod) -> 全市場OI
    for pid, tag in [("MTX", "mtx"), ("TMF", "tmf")]:
        rows = taifex_csv("https://www.taifex.com.tw/cht/3/futDataDown",
                          {"down_type": "1", "commodity_id": pid, **rng})
        for row in rows[1:]:
            if len(row) < 12 or "/" in row[2]:  # 排除價差組合
                continue
            oi = num(row[11])
            if oi is None:
                continue
            k = (row[0].strip(), tag)
            total[k] = total.get(k, 0) + oi
    out = {"mtx": [], "tmf": []}
    for (dt, prod), t_oi in sorted(total.items()):
        if t_oi <= 0 or (dt, prod) not in inst:
            continue
        i_long, i_short = inst[(dt, prod)]
        r_long, r_short = t_oi - i_long, t_oi - i_short
        ratio = round((r_long - r_short) / t_oi * 100, 2)  # 散戶多空比 %
        iso = dt.replace("/", "-")
        out[prod].append({"date": iso, "ratio": ratio,
                          "retail_long": r_long, "retail_short": r_short, "total_oi": t_oi})
    cache_set(key, out)
    return jsonify(out)


# ---------------- 集保 股權分散 (大戶/散戶) ----------------

TDCC_STATE = {"status": "idle", "date": None}
TDCC_PKL = os.path.join(CACHE_DIR, "tdcc.json")


def tdcc_download():
    TDCC_STATE["status"] = "downloading"
    try:
        r = requests.get("https://opendata.tdcc.com.tw/getOD.ashx?id=1-5", headers=UA, timeout=300)
        data = {}
        rdr = csv.reader(io.StringIO(r.content.decode("utf-8", errors="ignore")))
        header = next(rdr, None)
        data_date = None
        for row in rdr:  # 資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%
            if len(row) < 6:
                continue
            data_date = row[0]
            data.setdefault(row[1].strip(), []).append(
                [int(row[2]), num(row[3]) or 0, num(row[4]) or 0, num(row[5]) or 0])
        with open(TDCC_PKL, "w", encoding="utf-8") as f:
            json.dump({"date": data_date, "data": data}, f)
        TDCC_STATE["status"] = "ready"
        TDCC_STATE["date"] = data_date
    except Exception as e:
        TDCC_STATE["status"] = f"error: {str(e)[:80]}"


LEVEL_NAMES = ["1-999", "1千-5千", "5千-1萬", "1萬-1.5萬", "1.5萬-2萬", "2萬-3萬", "3萬-4萬", "4萬-5萬",
               "5萬-10萬", "10萬-20萬", "20萬-40萬", "40萬-60萬", "60萬-80萬", "80萬-100萬", "100萬以上", "差異數調整", "合計"]


@app.route("/api/chips")
def chips():
    code = re.sub(r"\W", "", request.args.get("code", ""))
    fresh = os.path.exists(TDCC_PKL) and time.time() - os.path.getmtime(TDCC_PKL) < 86400 * 6
    if not fresh:
        if TDCC_STATE["status"] != "downloading":
            threading.Thread(target=tdcc_download, daemon=True).start()
        if not os.path.exists(TDCC_PKL):
            return jsonify({"status": "downloading", "message": "集保股權分散表下載中 (首次約1-3分鐘), 請稍後重試"})
    with open(TDCC_PKL, encoding="utf-8") as f:
        db = json.load(f)
    rows = db["data"].get(code)
    if not rows:
        return jsonify({"error": f"查無 {code} 的股權分散資料"}), 404
    levels = []
    total_shares = 0
    big_shares = 0  # 400張(=40萬股)以上: 級距12-15
    for lv, people, shares, pct in sorted(rows):
        if 1 <= lv <= 15:
            levels.append({"level": LEVEL_NAMES[lv - 1], "people": people,
                           "lots": round(shares / 1000), "pct": pct})
            total_shares += shares
            if lv >= 12:
                big_shares += shares
    return jsonify({
        "status": "ready", "date": db["date"], "code": code, "levels": levels,
        "big_holder_pct": round(big_shares / total_shares * 100, 2) if total_shares else None,
        "retail_pct": round((1 - big_shares / total_shares) * 100, 2) if total_shares else None,
    })


# ---------------- 推薦標的 (觀點記錄卡) ----------------

@app.route("/api/recommendations")
def recommendations():
    if not os.path.exists(REC_PATH):
        return jsonify([])
    with open(REC_PATH, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/")
def home():
    return send_from_directory("static", "index.html")


if __name__ == "__main__":
    print("儀表板: http://127.0.0.1:5177")
    app.run(host="127.0.0.1", port=5177, debug=False)
