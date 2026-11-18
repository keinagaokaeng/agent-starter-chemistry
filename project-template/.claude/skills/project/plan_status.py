#!/usr/bin/env python3
"""PROJECT_PLAN.md を読み、ゴールまでの距離と期限までの見通しを定量的に計算する。

使い方:
    python3 plan_status.py                  # カレントフォルダの PROJECT_PLAN.md を詳しく表示
    python3 plan_status.py --brief          # 要約 2〜3 行（作業開始時の自動表示用）
    python3 plan_status.py --write          # plan/STATUS.md を書き出し、plan/history.jsonl に記録
    python3 plan_status.py <フォルダ>        # PROJECT_PLAN.md が無いフォルダなら、直下の各プロジェクトを一覧表示
    python3 plan_status.py --today 2026-12-01   # 日付を指定して試算

計算するもの（すべて PROJECT_PLAN.md の表から機械的に計算。推測はしない）:
    作業進捗      = 完了タスクの見込み時間 / 全タスクの見込み時間（中止を除く）
    見積もり倍率  = 完了タスクの実績時間 / 見込み時間（3 件以上で使用。未満なら 1.0）
    実績ペース    = 直近 28 日に完了したタスクの見込み時間 / 週
    完了予測日    = 今日 + 残り見込み時間 / 実績ペース
                    （実績が少ないうちは 残り×倍率 / 週あたりの作業時間 で計算し「計画値」と表示）
    期限までの余裕 = 期限までに使える時間 − 残り時間×倍率
    SPI           = 完了タスクの見込み時間 / 期日が今日以前のタスクの見込み時間（1.0 で計画どおり）
    品質達成率    = 品質ルーブリックの 現在点（目標で頭打ち）の合計 / 目標点の合計
    自動指標      = drafts/ 内の TODO 数、未確認文献（TODO: verify）の数

依存: Python 3.9 以上の標準ライブラリのみ。PROJECT_PLAN.md 以外のファイルは変更しない（--write 時の plan/ を除く）。
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

PLAN = "PROJECT_PLAN.md"

# --- しきい値（必要に応じて変更） ---------------------------------------------
VELOCITY_WINDOW_DAYS = 28      # 実績ペースを計算する期間
MIN_HISTORY_DAYS = 14          # これより短い間は「計画値」で予測
MIN_ACTUALS_FOR_RATIO = 3      # 見積もり倍率を使う最低件数
STALL_DAYS = 7                 # 進行中のまま止まっているとみなす日数
DECISION_WAIT_DAYS = 3         # 判断待ちが長いとみなす日数
RUBRIC_STALE_DAYS = 14         # 品質評価が古いとみなす日数
MAX_TASK_HOURS = 1.5           # これより大きいタスクは分割候補
SLIP_WARN_DAYS = 0             # 予測完了が期限をこれ以上超えたら「注意」
SLIP_DANGER_DAYS = 14          # 予測完了が期限をこれ以上超えたら「危険」
VAGUE_WORDS = ("検討", "進める", "考える", "調べる", "やる", "対応")

DONE, CANCEL, DOING, WAIT = "完了", "中止", "進行中", "判断待ち"
LEVEL = ["順調", "注意", "危険"]


# ---------------------------------------------------------------------------
# 読み取り
# ---------------------------------------------------------------------------
def parse_date(s):
    m = re.search(r"\d{4}-\d{2}-\d{2}", s or "")
    try:
        return dt.date.fromisoformat(m.group()) if m else None
    except ValueError:
        return None


def parse_num(s):
    m = re.search(r"\d+(?:\.\d+)?", (s or "").replace(",", ""))
    return float(m.group()) if m else None


def split_sections(text):
    out, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            cur = m.group(1)
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return out


def section(secs, prefix):
    for k, v in secs.items():
        if k.startswith(prefix):
            return v
    return []


def parse_table(lines):
    rows = [l for l in lines if l.strip().startswith("|")]
    if len(rows) < 2:
        return []

    def cells(l):
        return [c.strip() for c in l.strip().strip("|").split("|")]

    header = cells(rows[0])
    out = []
    for r in rows[2:]:
        c = cells(r)
        if not any(c):
            continue
        c += [""] * (len(header) - len(c))
        out.append(dict(zip(header, c)))
    return out


def get(row, *keys):
    """列名に keys のどれかを含む列の値（最初に見つかったもの）。"""
    for key in keys:
        for k, v in row.items():
            if k == key:
                return v
    for key in keys:
        for k, v in row.items():
            if key in k:
                return v
    return ""


def field(lines, label):
    for l in lines:
        m = re.match(r"^\s*-\s*" + re.escape(label) + r"[^:：]*[:：]\s*(.*)$", l)
        if m:
            return m.group(1).strip()
    return ""


def load(path):
    text = Path(path).read_text(encoding="utf-8")
    secs = split_sections(text)
    goal = section(secs, "ゴール")
    plan = {
        "name": (re.search(r"^#\s+PROJECT_PLAN\s*[—-]\s*(.+)$", text, re.M) or [None, Path(path).parent.name])[1],
        "deadline": parse_date(field(goal, "期限")),
        "start": parse_date(field(goal, "開始日")),
        "capacity": parse_num(field(goal, "週あたりの作業時間")),
        "checks_done": sum(1 for l in goal if re.match(r"^\s*-\s*\[[xX]\]", l)),
        "checks_all": sum(1 for l in goal if re.match(r"^\s*-\s*\[[ xX]\]", l)),
        "tasks": parse_table(section(secs, "タスク一覧")),
        "milestones": parse_table(section(secs, "マイルストーン")),
        "decisions": parse_table(section(secs, "判断待ち")),
        "rubric": parse_table(section(secs, "品質ルーブリック")),
        "next": "",
    }
    nxt = section(secs, "次の一歩")
    plan["next"] = field(nxt, "タスク") or next((l.strip("- ").strip() for l in nxt if l.strip().startswith("-")), "")
    return plan


# ---------------------------------------------------------------------------
# 計算
# ---------------------------------------------------------------------------
def analyze(plan, today, root):
    tasks = []
    for r in plan["tasks"]:
        tid = get(r, "ID").replace("★", "").strip()
        if not tid or tid.upper() == "TODO":
            continue
        tasks.append({
            "id": tid,
            "name": get(r, "タスク"),
            "crit": "★" in get(r, "ID"),
            "done_cond": get(r, "完了条件"),
            "ms": get(r, "MS", "マイルストーン"),
            "est": parse_num(get(r, "見込み")),
            "act": parse_num(get(r, "実績")),
            "due": parse_date(get(r, "期日")),
            "started": parse_date(get(r, "開始")),
            "finished": parse_date(get(r, "完了日")),
            "status": get(r, "状態") or "未着手",
        })
    live = [t for t in tasks if t["status"] != CANCEL]
    done = [t for t in live if t["status"] == DONE]
    est = lambda ts: sum(t["est"] or 0 for t in ts)

    total_h, done_h = est(live), est(done)
    remaining_h = total_h - done_h
    res = {"today": today, "n_tasks": len(live), "n_done": len(done),
           "total_h": total_h, "done_h": done_h, "remaining_h": remaining_h,
           "progress": done_h / total_h if total_h else None}

    # 見積もり倍率
    pairs = [(t["act"], t["est"]) for t in done if t["act"] and t["est"]]
    ratio = (sum(a for a, _ in pairs) / sum(e for _, e in pairs)) if len(pairs) >= MIN_ACTUALS_FOR_RATIO else 1.0
    res["ratio"], res["ratio_n"] = ratio, len(pairs)
    res["remaining_real_h"] = remaining_h * ratio

    # 実績ペース
    start = plan["start"] or min([t["started"] for t in tasks if t["started"]] or [today])
    elapsed = (today - start).days
    window = max(1, min(VELOCITY_WINDOW_DAYS, elapsed))
    recent = [t for t in done if t["finished"] and 0 <= (today - t["finished"]).days < window]
    velocity = est(recent) / window * 7 if recent else 0.0
    res["velocity"] = velocity
    cap = plan["capacity"]
    if elapsed >= MIN_HISTORY_DAYS and velocity > 0:
        res["forecast_mode"] = "実績"
        weeks = remaining_h / velocity
    elif cap:
        res["forecast_mode"] = "計画値"
        weeks = res["remaining_real_h"] / cap
    else:
        res["forecast_mode"] = None
        weeks = None
    res["forecast"] = today + dt.timedelta(days=round(weeks * 7)) if weeks is not None else None

    # 期限
    dl = plan["deadline"]
    res["deadline"] = dl
    if dl:
        weeks_left = max(0.0, (dl - today).days / 7)
        res["days_left"] = (dl - today).days
        res["capacity_left"] = weeks_left * cap if cap else None
        res["buffer_h"] = res["capacity_left"] - res["remaining_real_h"] if cap else None
        res["required_pace"] = res["remaining_real_h"] / weeks_left if weeks_left > 0 else None
        res["slip_days"] = (res["forecast"] - dl).days if res["forecast"] else None
    else:
        res.update(days_left=None, capacity_left=None, buffer_h=None, required_pace=None, slip_days=None)
    res["capacity"] = cap

    # SPI
    pv = est([t for t in live if t["due"] and t["due"] <= today])
    res["spi"] = done_h / pv if pv else None

    # マイルストーン予測（期日順に、手前のマイルストーンの残りも積み上げる）
    ms_rows = sorted(plan["milestones"], key=lambda r: parse_date(get(r, "期日")) or dt.date.max)
    cum, ms_out = 0.0, []
    for r in ms_rows:
        mid = get(r, "ID")
        if not mid or mid.upper() == "TODO":
            continue
        mts = [t for t in live if t["ms"] == mid]
        m_total, m_done = est(mts), est([t for t in mts if t["status"] == DONE])
        cum += (m_total - m_done)
        if res["forecast_mode"] == "実績":
            f = today + dt.timedelta(days=round(cum / velocity * 7))
        elif res["forecast_mode"] == "計画値":
            f = today + dt.timedelta(days=round(cum * ratio / cap * 7))
        else:
            f = None
        due = parse_date(get(r, "期日"))
        ms_out.append({"id": mid, "name": get(r, "マイルストーン"), "due": due,
                       "pct": m_done / m_total if m_total else None, "n": len(mts),
                       "forecast": f if m_total > m_done else None,
                       "late": (f - due).days if (f and due and m_total > m_done) else None})
    res["milestones"] = ms_out

    # 注意点
    res["overdue"] = [t for t in live if t["status"] != DONE and t["due"] and t["due"] < today]
    res["stalled"] = [t for t in live if t["status"] == DOING and t["started"] and (today - t["started"]).days > STALL_DAYS]
    open_dec = []
    for r in plan["decisions"]:
        did = get(r, "ID")
        if not did or get(r, "決定"):
            continue
        opened = parse_date(get(r, "起票"))
        open_dec.append({"id": did, "what": get(r, "決めること"), "age": (today - opened).days if opened else None})
    res["decisions"] = open_dec
    res["no_est"] = [t for t in live if t["est"] is None]
    res["too_big"] = [t for t in live if t["status"] != DONE and (t["est"] or 0) > MAX_TASK_HOURS]
    res["vague"] = [t for t in live if t["status"] != DONE and
                    (not t["done_cond"] or t["done_cond"].upper() == "TODO" or any(w in t["done_cond"] for w in VAGUE_WORDS))]

    # 品質
    rub = []
    for r in plan["rubric"]:
        tgt, cur = parse_num(get(r, "目標")), parse_num(get(r, "現在"))
        if not get(r, "ID") or tgt is None:
            continue
        evd = parse_date(get(r, "評価日"))
        rub.append({"id": get(r, "ID"), "name": get(r, "観点"), "target": tgt, "current": cur or 0.0,
                    "evidence": get(r, "根拠"), "stale": (evd is None) or (today - evd).days > RUBRIC_STALE_DAYS})
    res["rubric"] = rub
    tsum = sum(x["target"] for x in rub)
    res["quality"] = sum(min(x["current"], x["target"]) for x in rub) / tsum if tsum else None
    res["quality_gap"] = sum(max(0.0, x["target"] - x["current"]) for x in rub)

    # 自動指標（drafts/ の TODO）
    todo = verify = 0
    d = root / "drafts"
    if d.is_dir():
        for p in d.rglob("*"):
            if p.suffix.lower() in (".md", ".tex", ".txt") and p.is_file():
                try:
                    s = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                verify += len(re.findall(r"TODO:\s*verify", s, re.I))
                todo += len(re.findall(r"TODO", s))
    res["draft_todo"], res["draft_verify"] = (todo, verify) if d.is_dir() else (None, None)
    res["checks"] = (plan["checks_done"], plan["checks_all"])

    # 総合判定
    lv, why = 0, []

    def bump(level, msg):
        nonlocal lv
        lv = max(lv, level)
        why.append(msg)

    if res["slip_days"] is not None and res["slip_days"] > SLIP_DANGER_DAYS:
        bump(2, f"予測完了が期限を {res['slip_days']} 日超過")
    elif res["slip_days"] is not None and res["slip_days"] > SLIP_WARN_DAYS:
        bump(1, f"予測完了が期限を {res['slip_days']} 日超過")
    if res["buffer_h"] is not None and res["buffer_h"] < 0:
        bump(2, f"期限までの作業時間が {-res['buffer_h']:.1f} h 不足")
    if res["spi"] is not None and res["spi"] < 0.75:
        bump(2, f"SPI {res['spi']:.2f}（計画の 75% 未満）")
    elif res["spi"] is not None and res["spi"] < 0.9:
        bump(1, f"SPI {res['spi']:.2f}")
    if res["overdue"]:
        bump(1, f"期日超過タスク {len(res['overdue'])} 件")
    if res["stalled"]:
        bump(1, f"{STALL_DAYS} 日以上止まっているタスク {len(res['stalled'])} 件")
    old = [x for x in open_dec if x["age"] is not None and x["age"] > DECISION_WAIT_DAYS]
    if old:
        bump(1, f"{DECISION_WAIT_DAYS} 日以上の判断待ち {len(old)} 件")
    if not dl:
        bump(1, "期限が未設定")
    if not total_h:
        bump(1, "見込み時間のあるタスクがない")
    res["level"], res["why"] = lv, why
    return res


# ---------------------------------------------------------------------------
# 表示
# ---------------------------------------------------------------------------
def pct(x):
    return "—" if x is None else f"{x * 100:.0f}%"


def bar(x, width=20):
    if x is None:
        return ""
    n = round(max(0.0, min(1.0, x)) * width)
    return "█" * n + "░" * (width - n)


def d(x):
    return x.isoformat() if x else "—"


def brief(r, plan):
    parts = [f"[{LEVEL[r['level']]}] 作業 {pct(r['progress'])}"]
    if r["quality"] is not None:
        parts.append(f"品質 {pct(r['quality'])}")
    if r["forecast"]:
        s = f"予測完了 {d(r['forecast'])}（{r['forecast_mode']}）"
        if r["deadline"]:
            s += f" / 期限 {d(r['deadline'])}（{r['slip_days']:+d} 日）"
        parts.append(s)
    elif r["deadline"]:
        parts.append(f"期限 {d(r['deadline'])}（残り {r['days_left']} 日）")
    lines = [f"{plan['name']}: " + " | ".join(parts)]
    if r["why"]:
        lines.append("  要注意: " + "、".join(r["why"]))
    if plan["next"]:
        lines.append("  次の一歩: " + plan["next"])
    return "\n".join(lines)


def full(r, plan):
    o = [f"# プロジェクト状況 — {plan['name']}", "",
         f"基準日: {d(r['today'])}（`plan_status.py` による自動計算）", "",
         f"## 総合判定: {LEVEL[r['level']]}", ""]
    o += [f"- {w}" for w in r["why"]] or ["- 問題なし"]
    o += ["", "## ゴールまでの距離", "",
          f"| 指標 | 値 |", "|---|---|",
          f"| 作業進捗 | {bar(r['progress'])} {pct(r['progress'])}（{r['done_h']:.1f} / {r['total_h']:.1f} h, タスク {r['n_done']}/{r['n_tasks']}） |",
          f"| 残り作業 | 見込み {r['remaining_h']:.1f} h → 見積もり倍率 ×{r['ratio']:.2f}（n={r['ratio_n']}）で 実時間 {r['remaining_real_h']:.1f} h |"]
    if r["quality"] is not None:
        o.append(f"| 品質達成率 | {bar(r['quality'])} {pct(r['quality'])}（目標まで {r['quality_gap']:.0f} 点） |")
    c = r["checks"]
    if c[1]:
        o.append(f"| 完了の定義 | {c[0]} / {c[1]} 項目 |")
    if r["draft_todo"] is not None:
        o.append(f"| 原稿の TODO / 未確認文献 | {r['draft_todo']} / {r['draft_verify']} |")
    o += ["", "## 期限までの見通し", "", "| 指標 | 値 |", "|---|---|",
          f"| 期限 | {d(r['deadline'])}" + (f"（残り {r['days_left']} 日）" if r["days_left"] is not None else "") + " |",
          f"| 実績の完了ペース | {r['velocity']:.1f} h/週（直近 {VELOCITY_WINDOW_DAYS} 日に完了したタスクの見込み時間） |",
          f"| 予定の作業時間 | {r['capacity'] or '—'} h/週 |"]
    if r["required_pace"] is not None:
        o.append(f"| 期限に間に合う必要ペース | {r['required_pace']:.1f} h/週（実時間） |")
    mode = {"実績": "実績ペースが続いた場合", "計画値": "予定どおり作業した場合（実績がまだ少ないため）"}.get(r["forecast_mode"], "計算不可")
    o.append(f"| 完了予測日 | {d(r['forecast'])}（{mode}） |")
    if r["slip_days"] is not None:
        o.append(f"| 期限との差 | {r['slip_days']:+d} 日（＋は遅れ） |")
    if r["buffer_h"] is not None:
        o.append(f"| 時間の余裕 | {r['buffer_h']:+.1f} h（予定どおり週 {r['capacity']:g} h 作業した場合） |")
    if r["capacity"] and r["forecast_mode"] == "実績" and r["velocity"] < r["capacity"] * 0.5:
        o.append(f"| 計画と実績の差 | 完了ペースが予定の {r['velocity'] / r['capacity'] * 100:.0f}% → 作業時間の確保か範囲の縮小を検討 |")
    spi = "—" if r["spi"] is None else f"{r['spi']:.2f}"
    o.append(f"| SPI | {spi}（1.0 で計画どおり） |")
    if r["milestones"]:
        o += ["", "## マイルストーン", "", "| ID | マイルストーン | 期日 | 進捗 | 予測 | 差（日） |", "|---|---|---|---|---|---|"]
        for m in r["milestones"]:
            late = "—" if m["late"] is None else f"{m['late']:+d}"
            fc = "完了" if m["pct"] == 1 else d(m["forecast"])
            o.append(f"| {m['id']} | {m['name']} | {d(m['due'])} | {pct(m['pct'])} | {fc} | {late} |")
    if r["rubric"]:
        o += ["", "## 品質ルーブリック", "", "| ID | 観点 | 現在 / 目標 | 根拠 | 評価 |", "|---|---|---|---|---|"]
        for x in r["rubric"]:
            o.append(f"| {x['id']} | {x['name']} | {x['current']:.0f} / {x['target']:.0f} | {x['evidence'] or '（根拠なし）'} | "
                     f"{'要再評価' if x['stale'] else '最新'} |")
    issues = []
    issues += [f"期日超過: [{t['id']}] {t['name']}（期日 {d(t['due'])}）" for t in r["overdue"]]
    issues += [f"停滞: [{t['id']}] {t['name']}（開始 {d(t['started'])}）→ 分割か原因の確認を" for t in r["stalled"]]
    issues += [f"判断待ち: [{x['id']}] {x['what']}" + (f"（{x['age']} 日）" if x["age"] is not None else "") for x in r["decisions"]]
    issues += [f"分割候補（{MAX_TASK_HOURS} h 超）: [{t['id']}] {t['name']}（{t['est']} h）" for t in r["too_big"]]
    issues += [f"完了条件があいまい: [{t['id']}] {t['name']}" for t in r["vague"]]
    issues += [f"見込み時間なし: [{t['id']}] {t['name']}" for t in r["no_est"]]
    o += ["", "## 対応が必要なこと", ""] + ([f"- {i}" for i in issues] or ["- なし"])
    if plan["next"]:
        o += ["", "## 次の一歩", "", f"- {plan['next']}"]
    return "\n".join(o) + "\n"


def snapshot(r):
    return {"date": d(r["today"]), "progress": r["progress"], "done_h": r["done_h"], "total_h": r["total_h"],
            "remaining_real_h": round(r["remaining_real_h"], 2), "velocity": round(r["velocity"], 2),
            "forecast": d(r["forecast"]), "deadline": d(r["deadline"]), "slip_days": r["slip_days"],
            "spi": None if r["spi"] is None else round(r["spi"], 3), "quality": r["quality"],
            "level": LEVEL[r["level"]]}


def trend(hist_path):
    if not hist_path.exists():
        return ""
    rows = [json.loads(l) for l in hist_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(rows) < 2:
        return ""
    o = ["", "## 推移（最新 10 回）", "", "| 日付 | 作業進捗 | 品質 | 予測完了 | 期限との差 | 判定 |", "|---|---|---|---|---|---|"]
    for x in rows[-10:]:
        o.append(f"| {x['date']} | {pct(x['progress'])} | {pct(x['quality'])} | {x['forecast']} | "
                 f"{'—' if x['slip_days'] is None else format(x['slip_days'], '+d')} | {x['level']} |")
    return "\n".join(o) + "\n"


def portfolio(root, today):
    o = [f"# プロジェクト一覧（{d(today)}）", "", "| プロジェクト | 判定 | 作業 | 品質 | 予測完了 | 期限 | 次の一歩 |", "|---|---|---|---|---|---|---|"]
    found = False
    for sub in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        f = sub / PLAN
        if not f.exists():
            continue
        found = True
        try:
            plan = load(f)
            r = analyze(plan, today, sub)
            o.append(f"| {sub.name} | {LEVEL[r['level']]} | {pct(r['progress'])} | {pct(r['quality'])} | "
                     f"{d(r['forecast'])} | {d(r['deadline'])} | {plan['next'] or '—'} |")
        except Exception as e:  # 1 つのプロジェクトの不備で全体を止めない
            o.append(f"| {sub.name} | 読み取り失敗 | — | — | — | — | {e} |")
    return "\n".join(o) + "\n" if found else ""


def main():
    ap = argparse.ArgumentParser(description="PROJECT_PLAN.md の定量モニタリング")
    ap.add_argument("folder", nargs="?", default=".")
    ap.add_argument("--brief", action="store_true", help="要約のみ")
    ap.add_argument("--write", action="store_true", help="plan/STATUS.md と plan/history.jsonl を更新")
    ap.add_argument("--today", help="基準日 YYYY-MM-DD（試算用）")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    root = Path(a.folder).resolve()

    if not (root / PLAN).exists():
        out = portfolio(root, today)
        if out:
            print(out if not a.brief else "\n".join(l for l in out.splitlines() if l.startswith("| ") and "---" not in l))
        elif not a.brief:
            print(f"{PLAN} がありません。「計画を作って」とエージェントに頼んでください。")
        return 0

    plan = load(root / PLAN)
    r = analyze(plan, today, root)
    if a.brief:
        print(brief(r, plan))
        return 0
    hist = root / "plan" / "history.jsonl"
    if a.write:
        hist.parent.mkdir(exist_ok=True)
        rows = [l for l in (hist.read_text(encoding="utf-8").splitlines() if hist.exists() else [])
                if l.strip() and json.loads(l).get("date") != d(today)]
        rows.append(json.dumps(snapshot(r), ensure_ascii=False))
        hist.write_text("\n".join(rows) + "\n", encoding="utf-8")
    report = full(r, plan) + trend(hist)
    if a.write:
        (root / "plan" / "STATUS.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # 自動実行（フック）で作業を止めない
        print(f"[plan_status] 計算できませんでした: {e}", file=sys.stderr)
        sys.exit(0)
