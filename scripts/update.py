"""Mリーグ公式サイトの個人成績を取得し、オーナーごとの合計ポイントを docs/data.json に書き出す。

使い方:
    python scripts/update.py                 # 公式サイトから取得
    python scripts/update.py --html FILE     # 保存済みHTMLから集計(テスト用)

依存ライブラリなし(Python 3.9+ 標準ライブラリのみ)。
"""
import argparse
import difflib
import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PICKS_PATH = ROOT / "picks.json"
EVENTS_PATH = ROOT / "events.json"
DATA_PATH = ROOT / "docs" / "data.json"
STATS_URL = "https://m-league.jp/stats/?season={season}"
JST = timezone(timedelta(hours=9))


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (mleague-draft aggregator)"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8")


def text_of(fragment):
    s = html.unescape(re.sub(r"<[^>]+>", "", fragment))
    return re.sub(r"\s+", " ", s).strip()


def norm_name(name):
    return re.sub(r"[\s　]", "", name)


def to_number(s):
    s = s.replace("▲", "-").replace(",", "").replace("pt", "").replace("%", "").strip()
    if s in ("", "-", "—"):
        return 0.0
    return float(s)


def parse_stats(page):
    if not re.search(r'aria-selected="true">\s*<span class="c-tab__label-main">Regular', page):
        raise ValueError("レギュラーシーズンのタブが選択されたページではありません (stats_season を確認してください)")

    players = []
    for m in re.finditer(r'<section class="p-stats__team[^"]*" id="(T\d+)"[^>]*>(.*?)</section>', page, re.S):
        team_id, body = m.group(1), m.group(2)
        team = text_of(re.search(r'<h2 class="p-stats__teamName">(.*?)</h2>', body, re.S).group(1))
        rows = {}
        for tr in re.findall(r"<tr>(.*?)</tr>", body, re.S):
            label = text_of(re.search(r'<th scope="row">(.*?)</th>', tr, re.S).group(1))
            rows[label] = [text_of(c) for c in re.findall(r'<(?:td|th scope="col")>(.*?)</(?:td|th)>', tr, re.S)]
        for i, name in enumerate(rows["選手名"]):
            players.append({
                "name": name,
                "team": team,
                "team_id": team_id,
                "games": int(to_number(rows["試合数"][i])),
                "points": round(to_number(rows["ポイント"][i]), 1),
                "avg_rank": round(to_number(rows["平着"][i]), 2),
                "top": int(to_number(rows["1位"][i])),
                "last": int(to_number(rows["4位"][i])),
            })
    if len(players) < 30:
        raise ValueError(f"選手データが {len(players)} 人分しか取れませんでした。公式サイトの構造が変わった可能性があります")
    return players


def aggregate(picks, players):
    by_name = {norm_name(p["name"]): p for p in players}
    errors = []
    pick_count = {}
    owners = []
    for o in picks["owners"]:
        if len(o["players"]) != 4:
            errors.append(f"{o['name']}: 指名が {len(o['players'])} 人です (4人必要)")
        roster = []
        for raw in o["players"]:
            p = by_name.get(norm_name(raw))
            if p is None:
                hint = difflib.get_close_matches(norm_name(raw), by_name.keys(), n=3, cutoff=0.4)
                errors.append(f"{o['name']}: 「{raw}」が公式の選手一覧にいません" + (f" (候補: {', '.join(hint)})" if hint else ""))
                continue
            pick_count[p["name"]] = pick_count.get(p["name"], 0) + 1
            roster.append(p)
        owners.append({
            "name": o["name"],
            "total": round(sum(p["points"] for p in roster), 1),
            "players": [p["name"] for p in sorted(roster, key=lambda p: -p["points"])],
        })
    if errors:
        raise ValueError("picks.json に誤りがあります:\n  " + "\n  ".join(errors))
    for name, n in pick_count.items():
        if n > 1:
            print(f"注意: {name} が {n} 人のオーナーに重複指名されています", file=sys.stderr)

    owners.sort(key=lambda o: -o["total"])
    for i, o in enumerate(owners):
        o["rank"] = owners[i - 1]["rank"] if i and o["total"] == owners[i - 1]["total"] else i + 1

    owner_of = {}
    for o in owners:
        for name in o["players"]:
            owner_of.setdefault(name, []).append(o["name"])
    for p in players:
        p["owners"] = owner_of.get(p["name"], [])
    players.sort(key=lambda p: -p["points"])
    return owners, players


RANK_PRIZES = [30000, 20000, 10000, 5000, 0, -5000, -10000, -20000, -30000]
CATEGORIES = ["rank", "yakuman", "chombo", "scandal", "mvp", "last"]
EVENT_TYPES = {
    # type: (内訳の列, 表示名, 該当選手のオーナーが全員から受け取る(+)/全員に払う(-)額)
    "yakuman": ("yakuman", "役満", 1000),
    "chombo": ("chombo", "チョンボ", -1000),
    "scandal": ("scandal", "スキャンダル", -1000),
    "indicted": ("scandal", "起訴スキャンダル", -3000),
}
YAKUMAN_DEALT_IN = 3000  # 役満に放銃した選手のオーナーの支払額(1000allの代わり)


def load_events(path, players):
    if not path.exists():
        return []
    events = json.loads(path.read_text(encoding="utf-8"))
    by_name = {norm_name(p["name"]): p["name"] for p in players}
    errors = []
    for i, e in enumerate(events, 1):
        where = f"events.json {i}件目"
        if e.get("type") not in EVENT_TYPES:
            errors.append(f"{where}: type は {' / '.join(EVENT_TYPES)} のいずれか")
        for key in ("player", "dealt_in"):
            if key == "dealt_in" and not e.get(key):
                continue
            name = by_name.get(norm_name(e.get(key) or ""))
            if name is None:
                hint = difflib.get_close_matches(norm_name(e.get(key) or ""), by_name.keys(), n=3, cutoff=0.4)
                errors.append(f"{where}: 「{e.get(key)}」が公式の選手一覧にいません" + (f" (候補: {', '.join(hint)})" if hint else ""))
            else:
                e[key] = name
        if e.get("dealt_in") and e.get("type") != "yakuman":
            errors.append(f"{where}: dealt_in は役満のときだけ指定できます")
    if errors:
        raise ValueError("events.json に誤りがあります:\n  " + "\n  ".join(errors))
    return sorted(events, key=lambda e: e.get("date", ""))


def round_zero_sum(values):
    """合計がゼロの実数を、合計ゼロのまま整数に丸める"""
    out = {k: round(v) for k, v in values.items()}
    drift = sum(out.values())
    for k in sorted(values, key=lambda k: (out[k] - values[k]) * (1 if drift > 0 else -1), reverse=True)[:abs(drift)]:
        out[k] -= 1 if drift > 0 else -1
    return out


def settle(owners, players, events, final):
    names = [o["name"] for o in owners]
    owner_of = {p["name"]: p["owners"] for p in players}
    rows = {n: dict.fromkeys(CATEGORIES + ["total"], 0) for n in names}
    log = []

    def apply(category, effects, date, label, detail):
        for n, v in effects.items():
            rows[n][category] += v
        effects = {n: v for n, v in round_zero_sum(effects).items() if v}
        log.append({"date": date, "label": label, "detail": detail, "effects": effects})

    def all_pay(owner, amount):
        """owner が他の全オーナーから amount ずつ受け取る(負なら払う)"""
        eff = {n: -amount for n in names if n != owner}
        eff[owner] = amount * (len(names) - 1)
        return eff

    def merge(*effs):
        out = {}
        for eff in effs:
            for n, v in eff.items():
                out[n] = out.get(n, 0) + v
        return out

    # 順位賞(同点は該当順位の賞金を平均)
    i = 0
    while i < len(owners):
        j = i
        while j + 1 < len(owners) and owners[j + 1]["total"] == owners[i]["total"]:
            j += 1
        prize = sum(RANK_PRIZES[i:j + 1]) / (j - i + 1)
        for o in owners[i:j + 1]:
            rows[o["name"]]["rank"] = prize
        i = j + 1

    for e in events:
        category, label, amount = EVENT_TYPES[e["type"]]
        detail = e["player"] + (f" ← {e['dealt_in']}" if e.get("dealt_in") else "") + (f"（{e['note']}）" if e.get("note") else "")
        effs = []
        for w in owner_of[e["player"]]:
            dealers = [d for d in owner_of.get(e.get("dealt_in"), []) if d != w]
            if e["type"] == "yakuman" and dealers:
                eff = all_pay(w, amount)
                for d in dealers:  # 放銃者のオーナーは1000allの代わりに3000を払う
                    eff = merge(eff, {d: amount - YAKUMAN_DEALT_IN, w: YAKUMAN_DEALT_IN - amount})
                effs.append(eff)
            else:
                effs.append(all_pay(w, amount))
        apply(category, merge(*effs), e.get("date", ""), label, detail)

    # MVP・最下位(全選手の個人ポイント。指名されていない選手なら支払いなし。同点は按分)
    if sum(p["games"] for p in players) > 0:
        status = "確定" if final else "暫定"
        for category, label, amount, pick in (("mvp", "MVP", 1000, max), ("last", "最下位", -1000, min)):
            edge = pick(p["points"] for p in players)
            tied = [p for p in players if p["points"] == edge]
            effs = [all_pay(o, amount / len(tied)) for p in tied for o in p["owners"]]
            detail = "・".join(f"{p['name']} {p['points']:+.1f}" for p in tied)
            apply(category, merge(*effs), "", f"{label}（{status}）", detail)

    # 按分で出た端数を丸める(カテゴリごとに合計ゼロを保つ)
    for c in CATEGORIES:
        for n, v in round_zero_sum({n: rows[n][c] for n in names}).items():
            rows[n][c] = v
    for n in names:
        rows[n]["total"] = sum(rows[n][c] for c in CATEGORIES)

    return {
        "final": final,
        "rows": [dict(name=n, **rows[n]) for n in names],
        "log": log,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", help="公式サイトの代わりに読み込むHTMLファイル")
    args = ap.parse_args()

    picks = json.loads(PICKS_PATH.read_text(encoding="utf-8"))
    page = Path(args.html).read_text(encoding="utf-8") if args.html else fetch(STATS_URL.format(season=picks["stats_season"]))
    owners, players = aggregate(picks, parse_stats(page))
    events = load_events(EVENTS_PATH, players)
    settlement = settle(owners, players, events, picks.get("regular_season_finished", False))

    old = json.loads(DATA_PATH.read_text(encoding="utf-8")) if DATA_PATH.exists() else {}
    history = old.get("history", []) if old.get("season_label") == picks["season_label"] else []

    now = datetime.now(JST)
    total_games = sum(p["games"] for p in players)
    # 試合は夜なので、正午より前の取得は前日の試合として記録する
    game_day = (now - timedelta(hours=12)).strftime("%Y-%m-%d")
    snapshot = {"date": game_day, "games": total_games, "totals": {o["name"]: o["total"] for o in owners}}
    if total_games > 0:
        if history and history[-1]["date"] == snapshot["date"]:
            history[-1] = snapshot
        elif not history or history[-1]["games"] != total_games or history[-1]["totals"] != snapshot["totals"]:
            history.append(snapshot)

    data = {
        "title": picks["title"],
        "season_label": picks["season_label"],
        "owners": owners,
        "players": players,
        "history": history,
        "settlement": settlement,
    }
    # 成績に変化がなければファイルを書き換えない(無駄なコミットを防ぐ)
    if {k: old.get(k) for k in data} == data:
        print("変化なし")
        return
    data["updated_at"] = now.strftime("%Y-%m-%d %H:%M")
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    money = {r["name"]: r["total"] for r in settlement["rows"]}
    for o in owners:
        print(f"{o['rank']}位 {o['name']}: {o['total']:+.1f}pt  収支 {money[o['name']]:+,}")


if __name__ == "__main__":
    try:
        main()
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)
