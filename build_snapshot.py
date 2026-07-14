# -*- coding: utf-8 -*-
"""產生手機版分析結果靜態快照 -> docs/index.html
不需後端: 把當下的分析師績效/觀點回測算好, 資料內嵌進單一HTML檔。
每晚排程跑完後執行, push 到 GitHub Pages 即可用手機開網址看。
  用法: python build_snapshot.py
"""
import sys, os, io, json
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "dashboard"))
import app  # 重用回測邏輯

DOCS = os.path.join(BASE, "docs")
os.makedirs(DOCS, exist_ok=True)


def build():
    client = app.app.test_client()
    bt = client.get("/api/backtest").get_json()
    recs = client.get("/api/recommendations").get_json()
    data = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "analysts": bt.get("analysts", []),
        "views": bt.get("views", []),
        "recs": recs,
    }
    html = TEMPLATE.replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False))
    out = os.path.join(DOCS, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已產生 {os.path.relpath(out, BASE)}  ({len(data['views'])}筆觀點 / {len(data['analysts'])}位分析師 / 更新 {data['updated']})")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>分析師績效 — 手機版</title>
<style>
:root{--navy-950:#0b1220;--navy-900:#101a2e;--navy-700:#1e2f4d;--navy-600:#2a3f61;
--steel-400:#5b7699;--steel-300:#8ba3c2;--steel-100:#dbe4f0;--paper:#f4f6f9;--card:#fff;
--amber:#f0a63a;--amber-dark:#c97f1e;--good:#2f9e6b;--bad:#d9483a;--line:#e3e8f0;
--ink:#1a2332;--ink-soft:#5b6b85;--radius:10px;--shadow:0 1px 2px rgba(16,26,46,.06),0 6px 20px -8px rgba(16,26,46,.12)}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--paper);color:var(--ink);font-family:'Barlow','Microsoft JhengHei',system-ui,sans-serif;padding-bottom:40px}
.nav{background:linear-gradient(180deg,var(--navy-900),var(--navy-950));border-bottom:3px solid var(--amber);
padding:14px 16px;color:#fff;position:sticky;top:0;z-index:10}
.nav .t{font-size:17px;font-weight:700;display:flex;align-items:center;gap:8px}
.nav .mark{width:28px;height:28px;border-radius:7px;background:linear-gradient(150deg,var(--amber),var(--amber-dark));
color:var(--navy-950);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px}
.nav .u{font-size:11.5px;color:var(--steel-300);margin-top:3px}
.wrap{max-width:760px;margin:0 auto;padding:14px 12px}
h2{font-size:16px;margin:18px 4px 10px;font-family:'Barlow Condensed','Microsoft JhengHei',sans-serif}
.mono{font-family:'JetBrains Mono',Consolas,monospace}
.panel{background:var(--card);border-radius:var(--radius);box-shadow:var(--shadow);padding:12px;margin-bottom:12px}
.podium{display:flex;gap:8px;align-items:flex-end;justify-content:center;margin:4px 0 14px;flex-wrap:wrap}
.pod{border-radius:var(--radius);padding:12px 12px 14px;text-align:center;min-width:104px;flex:1;max-width:150px}
.pod .crown{font-size:20px}.pod .name{font-weight:700;font-size:13.5px;margin-top:3px}
.pod .stats{font-family:'JetBrains Mono',monospace;font-size:11.5px;margin-top:5px;line-height:1.7}
.pod .stats b{font-size:15px}
.pod-1{background:linear-gradient(160deg,#ffedbd,#f5c96b);box-shadow:0 0 18px rgba(240,166,58,.4),var(--shadow);border:1px solid #e8b64f;order:2}
.pod-2{background:linear-gradient(160deg,#f2f5fa,#cfd6e0);border:1px solid #bcc6d4;order:1}
.pod-3{background:linear-gradient(160deg,#f6e7d8,#dcb28b);border:1px solid #cba178;order:3}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{background:var(--navy-900);color:#fff;font-weight:500;font-size:11.5px;padding:7px 6px;text-align:right;white-space:nowrap}
th:first-child{text-align:left;border-radius:6px 0 0 6px}th:last-child{border-radius:0 6px 6px 0}
td{padding:6px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap;font-family:'JetBrains Mono',monospace;font-size:12px}
td:first-child{text-align:left;font-family:'Barlow','Microsoft JhengHei',sans-serif}
.scroll{overflow-x:auto}
.up{color:var(--bad)}.dn{color:var(--good)}
.badge{font-size:10.5px;padding:1px 7px;border-radius:9px;font-weight:600;display:inline-block}
.buy{background:#fdecea;color:var(--bad);border:1px solid #f2c4bf}
.sell{background:#e8f5ef;color:var(--good);border:1px solid #bfe3d2}
.st-win{background:var(--good);color:#fff}.st-loss{background:var(--bad);color:#fff}
.st-open{background:#fdf3e0;color:var(--amber-dark)}.st-force{background:#eef1f6;color:var(--ink-soft)}
.rt-A{background:var(--good);color:#fff}.rt-B{background:var(--amber);color:var(--navy-950)}
.rt-C{background:#eef1f6;color:var(--ink-soft)}.rt-D{background:var(--bad);color:#fff}
.reccard{border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin-bottom:8px}
.reccard .h{display:flex;justify-content:space-between;font-size:13.5px;font-weight:600;gap:6px;flex-wrap:wrap}
.reccard .b{font-size:11.5px;color:var(--ink-soft);margin-top:4px;line-height:1.6}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:6px}
.kpi{background:var(--card);border-radius:9px;box-shadow:var(--shadow);padding:9px 10px;border-top:3px solid var(--navy-600)}
.kpi.a{border-top-color:var(--amber)}.kpi.g{border-top-color:var(--good)}
.kpi .l{font-size:9.5px;letter-spacing:.8px;color:var(--ink-soft);text-transform:uppercase}
.kpi .v{font-family:'JetBrains Mono',monospace;font-size:19px;font-weight:600;margin-top:3px}
.hint{color:var(--ink-soft);font-size:11px;padding:5px 2px;line-height:1.6}
.notice{font-size:11px;color:var(--ink-soft);text-align:center;margin-top:18px;line-height:1.6}
.empty{text-align:center;padding:26px;color:var(--ink-soft)}
</style>
</head>
<body>
<div class="nav">
  <div class="t"><span class="mark">AT</span>分析師績效追蹤</div>
  <div class="u" id="upd"></div>
</div>
<div class="wrap">
  <div class="kpis" id="kpis"></div>
  <h2>🏆 分析師績效排行</h2>
  <div class="panel"><div class="podium" id="podium"></div><div class="scroll" id="atable"></div></div>
  <h2>觀點回測驗證</h2>
  <div class="panel"><div class="scroll" id="vtable"></div></div>
  <h2>目前追蹤標的</h2>
  <div id="recs"></div>
  <div class="notice">⚠ 本頁為歷史回測與績效歸因, 僅為分析輔助, 不構成投資建議; 系統永不代為下單。<br>
    資料每日更新一次 · 手機看到的是最近一次電腦運算的結果快照。</div>
</div>
<script>
const D = /*__DATA__*/;
const $ = id => document.getElementById(id);
const fmt = n => n==null?"—":n.toLocaleString("zh-TW",{maximumFractionDigits:2});
const stB = s => ({"達標":"st-win","停損":"st-loss","進行中":"st-open","等待收盤":"st-open","強制結案":"st-force"}[s]||"st-force");
$("upd").textContent = "資料更新: " + D.updated;

// KPI
const closed = D.views.filter(v=>v.closed), wins = closed.filter(v=>v.win);
const avg = closed.length ? closed.reduce((s,v)=>s+v.return_pct,0)/closed.length : null;
$("kpis").innerHTML = `
 <div class="kpi"><div class="l">觀點數</div><div class="v">${D.views.length}</div></div>
 <div class="kpi g"><div class="l">整體勝率</div><div class="v">${closed.length?(wins.length/closed.length*100).toFixed(0)+"%":"—"}</div></div>
 <div class="kpi a"><div class="l">平均報酬</div><div class="v ${(avg||0)>=0?"up":"dn"}">${avg==null?"—":(avg>=0?"+":"")+avg.toFixed(1)+"%"}</div></div>`;

// 頒獎台
const pod = D.analysts.slice(0,3), crowns=["👑","🥈","🥉"];
if(pod.length){
  $("podium").innerHTML = pod.map((a,i)=>`<div class="pod pod-${i+1}"><div class="crown">${crowns[i]}</div>
    <div class="name">${a.analyst}</div><div class="stats">勝率 <b>${a.win_rate==null?"—":a.win_rate+"%"}</b><br>
    ${a.avg_return==null?"":(a.avg_return>=0?"+":"")+a.avg_return+"% · "}評級 ${a.rating}${a.low_sample?" ※":""}</div></div>`).join("");
  $("atable").innerHTML = `<table><thead><tr><th>分析師</th><th>觀點</th><th>結案</th><th>勝率</th><th>均報酬</th><th>評級</th></tr></thead><tbody>`+
    D.analysts.map((a,i)=>`<tr><td>#${i+1} ${a.analyst}${a.low_sample?' <span class="badge rt-C">樣本不足</span>':""}</td>
      <td>${a.total}</td><td>${a.closed}</td><td>${a.win_rate==null?"—":a.win_rate+"%"}</td>
      <td class="${(a.avg_return||0)>=0?"up":"dn"}">${a.avg_return==null?"—":(a.avg_return>=0?"+":"")+a.avg_return+"%"}</td>
      <td><span class="badge rt-${a.rating}">${a.rating}</span></td></tr>`).join("")+`</tbody></table>
      <div class="hint">評級: A=勝率≥65%且樣本≥20 · B=≥55% · C=45–55% · D=<45% · ※=樣本<10統計信度不足</div>`;
} else { $("podium").innerHTML=""; $("atable").innerHTML='<div class="empty">尚無績效資料</div>'; }

// 觀點回測
if(D.views.length){
  $("vtable").innerHTML = `<table><thead><tr><th>標的</th><th>方向</th><th>分析師</th><th>發布</th><th>基準</th><th>停損</th><th>目標</th><th>報酬</th><th>狀態</th></tr></thead><tbody>`+
    D.views.map(v=>`<tr><td>${v.code} ${v.name||""}</td>
      <td><span class="badge ${v.direction==="買入"?"buy":"sell"}">${v.direction}</span></td>
      <td>${v.analyst}</td><td>${v.date.slice(5)}</td><td>${fmt(v.base_price)}</td>
      <td>${fmt(v.stop)}${v.stop_estimated?"*":""}</td><td>${fmt(v.target)}</td>
      <td class="${(v.return_pct||0)>=0?"up":"dn"}">${v.return_pct==null?"—":(v.return_pct>=0?"+":"")+v.return_pct+"%"}</td>
      <td><span class="badge ${stB(v.status)}">${v.status}</span></td></tr>`).join("")+`</tbody></table>
      <div class="hint">停損含 * 為系統依技術面推估 · 結案規則: 觸目標=達標/觸停損=停損/逾60天=強制結案</div>`;
} else $("vtable").innerHTML='<div class="empty">尚無觀點</div>';

// 推薦標的
if(D.recs.length){
  $("recs").innerHTML = D.recs.map(r=>`<div class="reccard"><div class="h">
    <span>${r.code} ${r.name} <span class="badge ${r.direction==="買入"?"buy":"sell"}">${r.direction}</span></span>
    <span class="badge rt-B">信心 ${r.confidence}/10</span></div>
    <div class="b">分析師: ${r.analyst} · ${r.date}<br>進場: ${r.entry||"—"}
    ${r.target?" · 目標: "+r.target:""}${r.stop?" · 停損: "+r.stop:""}</div></div>`).join("");
} else $("recs").innerHTML='<div class="empty">尚無推薦標的</div>';
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
