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


def get_stock_kline(code, months):
    """上市/上櫃個股日K, 回傳 [{time,open,high,low,close,volume}, ...] 由舊到新"""
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
        return out
    # 上櫃個股: 櫃買新版API (舊 st43_result.php 已停用)
    for d in month_starts(months):
        key = f"otcstk_{code}_{d:%Y%m}"
        rows = cache_get(key, None if is_past_month(d) else 600)
        if rows is None:
            try:
                r = requests.get("https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock",
                                 params={"code": code, "date": f"{d:%Y/%m/%d}", "response": "json"},
                                 headers=UA, timeout=20)
                tables = r.json().get("tables") or []
                rows = tables[0].get("data") or [] if tables else []
            except Exception:
                rows = []
            cache_set(key, rows)
        for row in rows:  # [日期,成交仟股,成交仟元,開,高,低,收,漲跌,筆數]
            o, h, l, c = num(row[3]), num(row[4]), num(row[5]), num(row[6])
            if None in (o, h, l, c):
                continue
            out.append({"time": roc_to_iso(row[0]), "open": o, "high": h, "low": l, "close": c,
                        "volume": num(row[1]) or 0})
    return out


@app.route("/api/stock_kline")
def stock_kline():
    code = re.sub(r"\W", "", request.args.get("code", ""))
    months = min(int(request.args.get("months", 6)), 24)
    if not code:
        return jsonify({"error": "缺少股票代號"}), 400
    return jsonify(get_stock_kline(code, months))


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

def merge_duplicates(recs):
    """同標的+同方向的觀點併成一筆: 分析師欄以「、」串接顯示多位推薦,
    保留信心較高者的價位設定, 日期取最早發布日(績效基準)"""
    groups = {}
    for r in recs:
        groups.setdefault((r.get("code"), r.get("direction")), []).append(r)
    out, changed = [], False
    for lst in groups.values():
        if len(lst) == 1:
            out.append(lst[0])
            continue
        changed = True
        lst.sort(key=lambda x: -(x.get("confidence") or 0))
        base = lst[0]
        names = []
        for r in sorted(lst, key=lambda x: x.get("id", 0)):
            for n in str(r.get("analyst", "")).split("、"):
                if n and n not in names:
                    names.append(n)
        base["analyst"] = "、".join(names)
        base["date"] = min(r.get("date", "") for r in lst if r.get("date"))
        for field in ("stop", "target", "support"):
            if base.get(field) is None:
                base[field] = next((r.get(field) for r in lst[1:] if r.get(field) is not None), None)
        base["note"] = (base.get("note") or "") + f"（{len(names)}位分析師共同推薦, 已合併）"
        out.append(base)
    out.sort(key=lambda x: x.get("id", 0))
    return out, changed


def load_recommendations():
    if not os.path.exists(REC_PATH):
        return []
    with open(REC_PATH, encoding="utf-8") as f:
        recs = json.load(f)
    changed = False
    next_id = max([r.get("id", 0) for r in recs], default=0) + 1
    for r in recs:                    # 舊資料補上 id, 供手動編輯定位
        if "id" not in r:
            r["id"] = next_id
            next_id += 1
            changed = True
    recs, merged = merge_duplicates(recs)
    if changed or merged:
        save_recommendations(recs)
    return recs


def save_recommendations(recs):
    with open(REC_PATH, "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=2)


@app.route("/api/recommendations")
def recommendations():
    return jsonify(load_recommendations())


@app.route("/api/recommendations/<int:rec_id>", methods=["PATCH"])
def update_recommendation(rec_id):
    """手動調整某筆觀點的停損/目標價 (傳 null 可清除手動值, 改回系統技術面推估)"""
    recs = load_recommendations()
    rec = next((r for r in recs if r["id"] == rec_id), None)
    if rec is None:
        return jsonify({"error": "找不到這筆觀點"}), 404
    data = request.get_json(force=True, silent=True) or {}
    for field in ("stop", "target"):
        if field in data:
            rec[field] = first_num(data[field]) if data[field] not in (None, "") else None
    save_recommendations(recs)
    return jsonify(rec)


@app.route("/api/recommendations/<int:rec_id>", methods=["DELETE"])
def delete_recommendation(rec_id):
    """手動刪除不想追蹤的觀點"""
    recs = load_recommendations()
    remain = [r for r in recs if r["id"] != rec_id]
    if len(remain) == len(recs):
        return jsonify({"error": "找不到這筆觀點"}), 404
    save_recommendations(remain)
    return jsonify({"ok": True, "deleted": rec_id})


# ---------------- 觀點回測 + 分析師績效歸因 ----------------

def first_num(x):
    """從數字或字串中取出第一個數值, 例 '980-1000' -> 980.0"""
    if isinstance(x, (int, float)):
        return float(x)
    m = re.search(r"\d+(?:\.\d+)?", str(x or ""))
    return float(m.group()) if m else None


def months_between(d1, d2):
    return (d2.year - d1.year) * 12 + (d2.month - d1.month) + 1


def technical_stop(klines, rec_date_iso, base, support, is_long):
    """分析師未提供停損時, 依規劃書「由系統依支撐位補建議, 並標註系統推估」自動計算:
    1. 有給支撐/壓力位 (support) 且方向合理 -> 直接採用
    2. 否則抓發布日之前近20個交易日的低點(做多)/高點(做空), 抓當作技術支撐, 抓抓略留1%緩衝
    3. 都沒有資料 -> 退回保守預設: 做多 base*0.93 (-7%) / 做空 base*1.07 (+7%)"""
    sup = first_num(support)
    if is_long:
        if sup and 0 < sup < base:
            return round(sup, 2), "支撐位(分析師提供)"
        before = [k["low"] for k in klines if k["time"] < rec_date_iso][-20:]
        if before:
            swing_low = min(before)
            if swing_low < base:
                return round(swing_low * 0.99, 2), "技術面(近20日低點)"
        return round(base * 0.93, 2), "系統預設(-7%)"
    else:
        if sup and sup > base:
            return round(sup, 2), "壓力位(分析師提供)"
        before = [k["high"] for k in klines if k["time"] < rec_date_iso][-20:]
        if before:
            swing_high = max(before)
            if swing_high > base:
                return round(swing_high * 1.01, 2), "技術面(近20日高點)"
        return round(base * 1.07, 2), "系統預設(+7%)"


def backtest_one(rec):
    """依規劃書結案規則回測單筆觀點:
    觸目標價=達標(勝) / 觸停損=停損(敗) / 超過60天=以現價強制結案 / 其餘=進行中"""
    out = {**rec}
    try:
        rec_date = datetime.strptime(rec["date"], "%Y-%m-%d").date()
    except Exception:
        out.update({"status": "資料錯誤", "error": "date 格式須為 YYYY-MM-DD"})
        return out
    code = re.sub(r"\W", "", rec.get("code", ""))
    months = min(months_between(rec_date, date.today()), 24)
    klines = get_stock_kline(code, months)
    after = [k for k in klines if k["time"] >= rec["date"]]
    if not after:
        # 有K線但都在發布日之前 = 發布後市場尚未交易(週末/假日/颱風假) -> 等待收盤
        status = "等待收盤" if klines else "無資料"
        out.update({"status": status, "days": (date.today() - rec_date).days})
        return out
    base = after[0]["close"]          # 發布日(或次一交易日)收盤 = 績效基準價
    is_long = rec.get("direction") != "賣出"
    stop, target = first_num(rec.get("stop")), first_num(rec.get("target"))
    stop_source = "分析師提供"
    if not stop:
        stop, stop_source = technical_stop(klines, rec["date"], base, rec.get("support"), is_long)
    out["stop_estimated"] = not bool(first_num(rec.get("stop")))
    out["stop_source"] = stop_source
    out["stop"] = stop                # 回測明細顯示的是「實際使用」的停損 (分析師給的或系統推估)
    status, close_price, close_date = "進行中", after[-1]["close"], after[-1]["time"]
    for k in after[1:]:               # 發布日之後逐日檢查觸價
        if is_long:
            if stop and k["low"] <= stop:
                status, close_price, close_date = "停損", stop, k["time"]
                break
            if target and k["high"] >= target:
                status, close_price, close_date = "達標", target, k["time"]
                break
        else:
            if stop and k["high"] >= stop:
                status, close_price, close_date = "停損", stop, k["time"]
                break
            if target and k["low"] <= target:
                status, close_price, close_date = "達標", target, k["time"]
                break
    days = (datetime.strptime(close_date, "%Y-%m-%d").date() - rec_date).days
    if status == "進行中" and (date.today() - rec_date).days > 60:
        status = "強制結案"           # 超過60天未觸發 -> 以當前價結案
    ret = (close_price - base) / base * 100
    if not is_long:
        ret = -ret
    out.update({
        "status": status, "base_price": round(base, 2), "close_price": round(close_price, 2),
        "close_date": close_date, "return_pct": round(ret, 2), "days": days,
        "closed": status in ("達標", "停損", "強制結案"),
        "win": status == "達標" or (status == "強制結案" and ret > 0),
    })
    return out


def analyst_rating(win_rate, n):
    """規劃書 5.3: A=勝率≥65%且樣本≥20 / B=55-65%或10-19筆穩定 / C=45-55% / D=<45%"""
    if n == 0:
        return "—"
    if win_rate >= 65 and n >= 20:
        return "A"
    if win_rate >= 55:
        return "B"
    if win_rate >= 45:
        return "C"
    return "D"


@app.route("/api/backtest")
def backtest():
    if not os.path.exists(REC_PATH):
        return jsonify({"views": [], "analysts": []})
    mtime = int(os.path.getmtime(REC_PATH))
    key = f"backtest_{mtime}"
    cached = cache_get(key, 600)
    if cached is not None:
        return jsonify(cached)
    recs = load_recommendations()
    views = [backtest_one(r) for r in recs]
    # 依分析師彙總 (僅已結案觀點計入勝率, 依規劃書)
    # 合併觀點的 analyst 為「甲、乙」多人串接 -> 拆開後每位都記入這筆成績
    by = {}
    expanded = [(name, v) for v in views
                for name in str(v.get("analyst") or "未知").split("、") if name]
    for name, v in expanded:
        a = by.setdefault(name, {
            "analyst": name, "total": 0, "closed": 0, "wins": 0,
            "returns": [], "days": [], "hi_total": 0, "hi_wins": 0, "open_returns": []})
        a["total"] += 1
        if v.get("closed"):
            a["closed"] += 1
            a["returns"].append(v["return_pct"])
            a["days"].append(v["days"])
            if v.get("win"):
                a["wins"] += 1
            if (v.get("confidence") or 0) >= 8:
                a["hi_total"] += 1
                if v.get("win"):
                    a["hi_wins"] += 1
        elif v.get("return_pct") is not None:
            a["open_returns"].append(v["return_pct"])
    analysts = []
    for a in by.values():
        n = a["closed"]
        win_rate = round(a["wins"] / n * 100, 1) if n else None
        analysts.append({
            "analyst": a["analyst"], "total": a["total"], "closed": n,
            "win_rate": win_rate,
            "avg_return": round(sum(a["returns"]) / n, 2) if n else None,
            "avg_days": round(sum(a["days"]) / n, 1) if n else None,
            "max_loss": round(min(a["returns"]), 2) if a["returns"] else None,
            "hi_win_rate": round(a["hi_wins"] / a["hi_total"] * 100, 1) if a["hi_total"] else None,
            "open_avg_return": round(sum(a["open_returns"]) / len(a["open_returns"]), 2) if a["open_returns"] else None,
            "rating": analyst_rating(win_rate or 0, n),
            "low_sample": n < 10,     # 規劃書: 樣本<10 標註統計信度不足
        })
    analysts.sort(key=lambda x: (x["win_rate"] or -1, x["avg_return"] or -999), reverse=True)
    result = {"views": views, "analysts": analysts}
    cache_set(key, result)
    return jsonify(result)


@app.route("/")
def home():
    return send_from_directory("static", "index.html")


if __name__ == "__main__":
    print("儀表板: http://127.0.0.1:5177")
    app.run(host="127.0.0.1", port=5177, debug=False)
