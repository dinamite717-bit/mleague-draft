# Mリーグ ドラフト集計

9人のオーナーがチーム関係なく4選手ずつ指名し、指名選手のレギュラーシーズン個人ポイントの合計を競うための集計ページ。
順位賞と、役満・チョンボなどのボーナスによる収支も計算して表示する。

- 成績は [M.LEAGUE公式 チーム成績表](https://m-league.jp/stats) から毎日自動取得
- GitHub Actions(集計) + GitHub Pages(公開) で **費用0円**
- 閲覧はURLを共有するだけ(スマホ対応)

## 構成

| ファイル | 役割 |
|---|---|
| `picks.json` | オーナー名と指名選手 |
| `events.json` | 役満・チョンボ・スキャンダルの記録(手入力) |
| `scripts/update.py` | 公式サイトから取得して `docs/data.json` を作る(標準ライブラリのみ) |
| `docs/index.html` | 表示ページ(順位表・推移グラフ・選手ランキング) |
| `docs/data.json` | 集計結果と日ごとの推移(自動生成) |
| `.github/workflows/update.yml` | 毎日 0:30 / 8:00 JST に自動更新 |

## 初期設定(1回だけ)

1. GitHubで**Public**リポジトリを作成(無料プランでPagesを使うにはPublicが必要)
2. このフォルダの中身をpush
3. リポジトリの Settings → Pages → Source を「Deploy from a branch」、Branch を `main` / `/docs` にして Save
4. Settings → Actions → General → Workflow permissions を「Read and write permissions」にして Save
5. Actions タブ → 「成績更新」→ Run workflow で1回動かして確認
6. 数分後 `https://<ユーザー名>.github.io/<リポジトリ名>/` が表示されたら、そのURLをオーナーに共有

## 指名選手の登録・変更

`picks.json` を編集してpush(GitHubの画面上で直接編集してもOK)。pushすると自動で再集計される。

- 選手名は公式サイトの表記どおり。姓名間のスペースの有無は問わない
- 名前が見つからない・4人でない場合はActionsが失敗し、GitHubからメールが届く(ログに候補名を表示)
- 同じ選手を複数オーナーが指名した場合は警告のみ(集計はする)

## ルール(収支)

**順位賞**(レギュラーシーズン終了時の合計pt順位。同点は該当順位の賞金を平均)

| 1位 | 2位 | 3位 | 4位 | 5位 | 6位 | 7位 | 8位 | 9位 |
|---|---|---|---|---|---|---|---|---|
| +30000 | +20000 | +10000 | +5000 | 0 | -5000 | -10000 | -20000 | -30000 |

**ボーナス**(「all」は他の8人全員と1人ずつやりとり。指名されていない選手が該当した場合は発生しない)

| 項目 | 内容 | 入力 |
|---|---|---|
| 役満 | +1000all。放銃した選手のオーナーは1000の代わりに3000を払う(上がった側 +10000、放銃側 -3000) | events.json |
| チョンボ | -1000all | events.json |
| スキャンダル | -1000all | events.json |
| 起訴スキャンダル | -3000all | events.json |
| MVP | 全40選手の個人pt1位のオーナーが +1000all(同点は按分) | 自動 |
| 最下位 | 全40選手の個人pt最下位のオーナーが -1000all(同点は按分) | 自動 |

対象はすべてレギュラーシーズンのみ。同じオーナーの選手どうしで役満の放銃があった場合は通常の1000allになる。
計算は `scripts/update.py` の `settle()`。

## 役満・チョンボ・スキャンダルの記録

`events.json` に追記してpush(GitHubの画面上で編集してOK)。

```json
[
  { "date": "2026-10-14", "type": "yakuman", "player": "佐々木寿人", "dealt_in": "多井隆晴", "note": "大三元" },
  { "date": "2026-10-20", "type": "yakuman", "player": "園田賢", "note": "四暗刻ツモ" },
  { "date": "2026-11-02", "type": "chombo", "player": "堀慎吾" },
  { "date": "2026-12-01", "type": "scandal", "player": "○○" },
  { "date": "2026-12-05", "type": "indicted", "player": "○○" }
]
```

- `type`: `yakuman`(役満) / `chombo`(チョンボ) / `scandal`(スキャンダル) / `indicted`(起訴スキャンダル)
- `dealt_in`: 役満の放銃者。ツモなら書かない
- `note`: 任意のメモ(役名など)。ページに表示される
- 選手名のスペースは有無どちらでもよい

## シーズン終了時

レギュラーシーズンが終わったら `picks.json` の `"regular_season_finished"` を `true` にする。
ページの「収支(暫定)」「MVP(暫定)」が「確定」表示になる。

## 手元での確認

```bash
python scripts/update.py
python -m http.server 8000 -d docs
```

ブラウザで http://localhost:8000 を開く。

## 新シーズンのとき

`picks.json` の `title` / `season_label` / `stats_season` と指名を更新する。
`stats_season` は公式 stats ページの「レギュラーシーズン」タブのURL末尾(`?season=L001_S025` の `L001_S025`)。
`season_label` を変えると推移グラフの履歴はリセットされる。

## 注意

- 集計対象はレギュラーシーズンのみ(セミファイナル・ファイナルは含めない)
- 公式サイトのHTML構造が変わると取得に失敗する(Actions失敗メールで気づける)。その場合は `parse_stats()` を修正
- GitHubは**60日間リポジトリに更新がないと定期実行を自動停止**する。シーズン中は毎日コミットされるので問題ないが、オフシーズン明けは Actions タブで再有効化が必要な場合がある
