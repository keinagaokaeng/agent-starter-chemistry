# AI エージェント スターターキット（化学研究向け・最小構成）

Claude Code などの AI エージェントを、論文執筆・データ解析・実験の段取りに使うための最小構成です。
方針は 2 つです。

1. **勝手にファイルを消させない・許可していない操作をさせない**
2. **考え込んで止まらない**: ゴール → 作業分解（WBS）→ マイルストーン → 次の一歩 を、エージェントが提案し、研究者は選ぶだけ

最初に入れるファイルは 7 つだけです。それ以外は、必要になったときに [7. 必要になったら追加するもの](#7-必要になったら追加するもの) から足してください。

---

## 1. 中身

```
project-template/              ← 研究フォルダにまるごとコピーする
├── AGENTS.md                  ← 研究室のルール（全エージェント共通の正本）。TODO を埋める
├── CLAUDE.md                  ← Claude Code の入口（AGENTS.md を読み込むだけ）
├── PROJECT_PLAN.md            ← 計画書（ゴール・マイルストーン・タスク・品質・進捗ログ）
├── .agent-guard/
│   └── guard_destructive.py   ← 削除・上書き系コマンドを止める（どのエージェントでも使える）
└── .claude/
    ├── settings.json          ← 権限・サンドボックス・フック（Claude Code の安全設定）
    └── skills/project/
        ├── SKILL.md           ← 計画づくり・次の一歩・状況確認・品質採点の手順
        └── plan_status.py     ← 進捗・完了予測・期限までの余裕を計算する
```

`.` で始まるファイルは Finder で見えません（`Cmd + Shift + .` で表示）。

| 種類 | ファイル | 強制力 |
|---|---|---|
| 指示（お願い） | `AGENTS.md`, `SKILL.md` | 守る努力はするが保証ではない |
| 強制 | `settings.json`, `guard_destructive.py` | システムが止める |
| 計算 | `plan_status.py` | 毎回同じ方法で計算（エージェントの推測に頼らない） |

---

## 2. 必要なもの

1. **Claude の有料プラン**（Pro / Max / 機関の Team・Enterprise）と **Claude Code**:
   ```
   curl -fsSL https://claude.ai/install.sh | bash
   ```
   VS Code の拡張機能「Claude Code」を使うと差分を見ながら承認できます。
   （ChatGPT / Codex / Cursor を使う場合は [7-F](#f-他のエージェントを使う) を参照）
2. **Python 3**（macOS には通常入っています）。**git** は推奨。
3. **所属機関の規定の確認**: エージェントに読ませた内容はクラウドで処理されます。未発表データ・特許出願前の内容を扱ってよいか確認してください。
   プランのプライバシー設定（会話をモデル改善に使うか）も確認してください。

---

## 3. 導入手順

1. 研究用フォルダを 1 つ決める（例: `~/Research/CatalysisProject`）。**ホームフォルダ全体やデスクトップでは起動しない。**
2. `project-template/` の中身をコピーし、作業用のフォルダを作る。
   ```
   cp -R project-template/. ~/Research/CatalysisProject/
   cd ~/Research/CatalysisProject
   mkdir -p data/raw data/processed scripts results notes drafts refs
   ```
3. 生データを `data/raw/` に入れ、**読み取り専用**にする（一番確実な防御）。
   ```
   chmod -R a-w data/raw        # 追加するときだけ chmod -R u+w data/raw で戻す
   ```
4. （推奨）`git init && git add -A && git commit -m "initial"`（[7-B](#b-git-で原稿とスクリプトを守る) の `.gitignore` を先に入れる）
5. `claude` で起動し、`/permissions`（ルール）と `/hooks`（フック）を確認する。
6. [5. 動作確認テスト](#5-動作確認テスト) を行う。
7. 「AGENTS.md の TODO を一緒に埋めて」→「計画を作って」の順に頼む。
   論文を書く場合は、AGENTS.md の「論文プロジェクト」節（基本情報、中心となる主張、章構成と状況、主張の範囲、品質基準など）も一緒に埋めると、
   計画（WBS）と品質ルーブリックを章構成から自動で組み立てられます。論文を書かないプロジェクトではこの節は消してかまいません。

---

## 4. 安全の仕組み

| 層 | 内容 | 防げること |
|---|---|---|
| ① OS の読み取り専用 | `chmod -R a-w data/raw` | 生データの変更・削除（誤操作も含む） |
| ② バックアップ / git | Time Machine、機関のクラウド、git | 万一のとき元に戻せる |
| ③ サンドボックス | コマンドは**このフォルダの外に書き込めない**。通信は PyPI / conda / GitHub のみ。サンドボックス外での実行は不可 | フォルダ外のファイル、未許可の通信 |
| ④ 禁止ルール | `rm -rf`、`find -delete`、`sudo`、`ssh`、`git reset --hard`、強制 push、`data/raw` への書き込み、鍵・`.env` の読み取り | 典型的な危険操作 |
| ⑤ 確認ルール | `rm`、`mv`、`git push`、`curl`、インストール、Web 検索、**ファイル編集**は毎回確認 | 意図しない削除・通信 |
| ⑥ ガードフック | コマンド全体を検査（`cd x && rm -r y`、`python -c "shutil.rmtree(...)"` なども止める） | ④⑤のすり抜け |
| ⑦ 全自動モードの無効化 | `disableBypassPermissionsMode` | 確認なしでの暴走 |

**限界**: ④〜⑥はコマンドの文字列を見ています。エージェントが書いた**スクリプトの中の削除処理**は検出できません。
`Esc` 2 回 / `/rewind` で戻せるのは**ファイル編集だけ**で、コマンドで消したものは戻りません。だから①②が必須です。

**運用**: 確認画面で「Yes, and don't ask again」を安易に選ばない（特に `rm`, `mv`, `python`）。大きな作業は Plan モード（`Shift + Tab`）で計画を見てから。
慣れて確認が多すぎると感じたら、`settings.json` の `autoAllowBashIfSandboxed` を `true` にできます（④〜⑥は有効なまま）。

---

## 5. 動作確認テスト

ダミーで試します（本物のデータでは試さない）。
```
mkdir -p results/_guard_test && echo test > results/_guard_test/dummy.txt
python3 .agent-guard/guard_destructive.py --check "rm -r results/_guard_test"     # deny と出ればガードは動作
```
エージェントに次を頼み、期待どおりか確認します。

| 依頼 | 期待 |
|---|---|
| 「`rm -r results/_guard_test` を実行して」 | 禁止 |
| 「`cd results && rm -rf _guard_test` を実行して」 | 禁止（フックが効いている） |
| 「`results/_guard_test/dummy.txt` を rm で消して」 | 確認が出る |
| 「`data/raw/` に test.txt を作って」 | 禁止 / 失敗 |
| 「`curl https://example.com` を実行して」 | 確認 / 拒否 |

1 つでも違えば、設定を見直すまで本物のデータでは使わないでください。最後に自分で `rm -r results/_guard_test`。

---

## 6. プロジェクトの進め方

```
ゴール（期限・完了の定義・週あたりの作業時間）
  └ マイルストーン（2〜6 週間ごと。完了の判定方法つき）
      └ WBS: 成果物 → ワークパッケージ → タスク（1 回 25〜90 分、完了条件が目で確認できる）
          └ 次の一歩（最初の 5 分でやることまで具体的に）
```

| 場面 | 言うこと（Claude Code では `/project` でも可） |
|---|---|
| 最初に 1 回 | 「計画を作って。質問は 1 つずつ、選択肢と推奨を付けて。分からない項目は仮の値で進めて」 |
| 毎回の始め | 「次の一歩は？」 |
| 終わるとき | 「今日はここまで。完了条件を確認して計画を更新し、次回の最初の 5 分を書いておいて」 |
| 止まったとき | 「1.1.4 が進まない。今日 15 分でできる最初の一手を 1 つ提案して」 |
| 状況確認 | 「状況は？ 期限に間に合う？ 間に合わないなら打ち手を効果の数値付きで 3 つ」 |
| 週 1 回 | 「週次レビューして。品質は根拠付きで採点し直して、確定は私に聞いて」 |

**定量モニタリング**（`plan_status.py` が `PROJECT_PLAN.md` の表から計算）: 作業進捗 %、残り時間（実績/見込みの倍率で補正）、
実績ペース、完了予測日、期限との差、時間の余裕、SPI（1.0 で計画どおり）、マイルストーンごとの予測、期日超過・停滞・判断待ち、
大きすぎるタスクやあいまいな完了条件の指摘、総合判定（順調 / 注意 / 危険）。Claude Code では起動時に要約が自動表示されます。

**定性面の客観評価**（品質ルーブリック）: 「良い論文」などの目標を 0〜3 点の**観察できる基準**で採点（例: 「全数値に出典 CSV がある」
「指導教員が大きな修正なしと回答」）。根拠必須、迷ったら低いほう、確定は研究者。原稿中の `TODO` と `TODO: verify` は自動で数えます。

**その他のプロンプトの型**: 目的・対象ファイル・制約・ほしい出力を書き、最後に「**まず計画だけ見せて。実行は私が OK してから**」。

| 避ける | 代わりに |
|---|---|
| 「いい感じに整理して」 | 「整理案を表で見せて。移動はしないで」 |
| 「データを綺麗にして」 | 「外れ値の候補と基準を提案して。除外はしないで」 |
| 「参考文献を 10 本追加して」 | 自分で集めた PDF / BibTeX を渡して整理を頼む |
| 「全部許可するので自動でやって」 | Plan モードで計画を確認してから |

---

## 7. 必要になったら追加するもの

**追加の仕方**: 下の表の「頼み方」をエージェントに伝えれば作ってくれます。
ただし **安全設定（`settings.json`、`.agent-guard/`、`.codex/`、`.cursor/`）はエージェントが書き換えられない設定**なので、
下の例を研究者が自分で貼ってください。追加したら `AGENTS.md` にも 1 行書いておくと、どのエージェントも参照します。

| # | 追加するもの | いつ必要か | 方法 |
|---|---|---|---|
| A | 作業別の手順書（スキル） | 同じ種類の依頼を何度もするようになったら | エージェントに頼む（下記） |
| B | git の保護（`.gitignore`） | git を使い始めるとき | 下の例を貼る |
| C | 全フォルダ共通の安全設定 | 複数の研究フォルダで使うとき | 下の例を `~/.claude/settings.json` に統合 |
| D | 複数プロジェクトの管理 | プロジェクトが 2 つ以上になったら | フォルダ構成を合わせる＋エージェントに頼む |
| E | 計画の記入例 | 計画の書き方の見本が欲しいとき | エージェントに頼む |
| F | 他のエージェント（ChatGPT / Codex / Cursor） | Claude Code 以外を使うとき | 下の例を貼る |

### A. 作業別の手順書（スキル）

`.claude/skills/<名前>/SKILL.md` に置くと、関係する依頼のときに自動で読み込まれます（Claude Code）。頼み方の例:

| スキル | 頼み方 |
|---|---|
| 論文執筆 `paper-writing` | 「論文の執筆・校閲・査読回答用のスキルを作って。編集前に方針を示す、数値は results/ の CSV と照合、文献は渡したものだけ、誇張表現を避ける、セクションごとの要点（Intro: 背景→ギャップ→貢献 など）を入れて」 |
| データ解析 `analyze-data` | 「スペクトル・速度論データの解析スキルを作って。確認→計画→1 ファイルで試行→全体、生データは読むだけ、CSV と図を出力、パラメータとバージョンを results/README.md に記録、を入れて」 |
| 実験記録 `experiment-record` | 「実験ノートのスキルを作って。notes/experiments/日付_ID.md、試薬表（CAS・ロット・mmol・equiv）、安全確認欄、書いていない値は TODO のまま、を入れて」 |
| 論文の表記ルール | 「drafts/ を扱うときだけ読む表記ルールを .claude/rules/chemistry-writing.md に作って。frontmatter の paths で drafts/** と *.tex を指定。化合物番号、NMR の書式、単位、引用のルールを入れて」 |

### B. git で原稿とスクリプトを守る

研究フォルダに `.gitignore` を作り、未発表データを git に入れないようにします。

<details><summary>.gitignore の例</summary>

```
# 未発表データは git に入れない
data/
results/
*.csv
*.xlsx
# スペクトル・構造・計算出力
*.jdx
*.fid
*.mnova
*.raw
*.cif
*.cdx
*.mol
*.sdf
*.xyz
*.chk
# 文献 PDF・アーカイブ
refs/*.pdf
*.zip
# 秘密情報・個人設定
.env*
*.pem
*.key
.claude/settings.local.json
# Python / OS
.venv/
__pycache__/
.DS_Store
```
</details>

さらに「コミット時にデータや API キーが含まれていたら止めるフックを作って」と頼むこともできます（作られたスクリプトは読んでから登録してください）。

### C. 全フォルダ共通の安全設定

`~/.claude/settings.json` に統合します（**既にある場合は上書きせず、項目を足す**）。

<details><summary>~/.claude/settings.json の例</summary>

```json
{
  "permissions": {
    "disableBypassPermissionsMode": "disable",
    "deny": [
      "Read(~/.ssh/**)", "Read(~/.aws/**)", "Read(~/.config/gh/**)", "Read(~/.git-credentials)",
      "Read(~/Library/Keychains/**)", "Read(**/.env*)", "Edit(**/.env*)", "Read(**/*.pem)",
      "Bash(rm -rf:*)", "Bash(rm -fr:*)", "Bash(sudo:*)"
    ],
    "ask": ["Bash(rm:*)", "Bash(git push:*)", "Bash(curl:*)", "Bash(wget:*)"]
  },
  "sandbox": { "enabled": true, "autoAllowBashIfSandboxed": false }
}
```
</details>

### D. 複数のプロジェクトを並行して進める

プロジェクトごとにフォルダを分け、それぞれに `project-template/` を入れます。
```
~/Research/
├── CatalysisProject/   （PROJECT_PLAN.md など一式）
└── KineticsReview/     （PROJECT_PLAN.md など一式）
```
- **一覧**: `python3 CatalysisProject/.claude/skills/project/plan_status.py ~/Research` で、直下の全プロジェクトの判定・進捗・予測・次の一歩が 1 つの表に出ます。
- **どれをやるか**: 親フォルダでエージェントを起動して「どのプロジェクトから進める？」と聞くと、一覧から推奨付きで提案します。
- **時間の配分**（必要になったら）: 各計画の「週あたりの作業時間」は別々に書くため、合計が実際の時間を超えても気付けません。
  そうなったら、「~/Research/PORTFOLIO.md に週の総作業時間と各プロジェクトへの配分（h または %）・優先度・プロジェクト間の依存を書く形式を作り、
  plan_status.py が配分後の時間で予測し、配分の合計が総作業時間を超えたら警告するように拡張して」と頼んでください。

### E. 計画の記入例

「架空の化学論文プロジェクトで、PROJECT_PLAN.md の記入例を examples/PROJECT_PLAN_example.md に作って。plan_status.py で計算できる形で」と頼むと、
見本と計算結果を確認できます。

### F. 他のエージェントを使う

`AGENTS.md`、`PROJECT_PLAN.md`、`plan_status.py`、`guard_destructive.py` はそのまま使えます。差し替えるのは入口と安全設定だけです。
各ツールの仕様は変わりやすいので、導入後は必ず [5. 動作確認テスト](#5-動作確認テスト) を行ってください（2026 年 11 月時点の公式ドキュメントで確認）。

| | Claude Code | OpenAI Codex | Cursor | ChatGPT（チャット） |
|---|---|---|---|---|
| ルール | `CLAUDE.md` → `AGENTS.md` | `AGENTS.md` をそのまま読む | `AGENTS.md` をそのまま読む | プロジェクトの「指示」に貼る |
| 手順書 | `.claude/skills/` | `.agents/skills/` にコピー | `AGENTS.md` から参照 | ファイルをアップロード |
| 安全設定 | `settings.json` | `.codex/config.toml` + `.codex/rules/` | `.cursor/hooks.json` + 設定画面 | 不要（PC を操作しない） |
| ガード | `--format claude` | `--format codex` | `--format cursor` | 不要 |

<details><summary>ChatGPT（チャット画面）だけを使う場合</summary>

ChatGPT のチャットは PC のファイルを操作しないので、削除の心配はほぼありません。注意するのは**何をアップロードするか**です。
「プロジェクト」を作り、「指示」に次を貼ります。`SKILL.md` と `PROJECT_PLAN.md` をプロジェクトファイルにアップロードすれば、同じ進め方ができます。
ただし数値は ChatGPT に計算させず、手元で `python3 plan_status.py` を実行して結果を貼ってください。

```
あなたは化学研究者の論文執筆・データ解析・実験の段取りを手伝うアシスタントです。
- 数値・データ・文献を作らない。推測で埋めず「TODO」として質問する。文献は私が渡したものだけを使う。
- 論文に書く数値には出典（どのファイルのどの値か）を添える。外れ値の除外などは基準を示して承認を得てから。
- 大きな作業はまず計画を示す。質問は 1 回に 1 つ、選択肢 2〜3 個と推奨を付ける。
- 進め方は添付の SKILL.md（ゴール → WBS → マイルストーン → 次の一歩）に従う。
- 実験手順には危険性を併記し、SDS と所属機関の安全規則での確認が必要と明記する。
- 誇張表現は根拠がある場合のみ。返答は日本語、論文本文は英語。
```
</details>

<details><summary>OpenAI Codex（ChatGPT の有料プランで使えるエージェント）</summary>

1. スキルをコピー: `mkdir -p .agents && cp -R .claude/skills .agents/skills`（`AGENTS.md` 内のパスも `.agents/skills/` に読み替え）
2. `.codex/config.toml` を作る:
   ```toml
   sandbox_mode = "read-only"        # 慣れたら "workspace-write"。"danger-full-access" は使わない
   approval_policy = "on-request"

   [sandbox_workspace_write]
   network_access = false

   [features]
   hooks = true

   [[hooks.PreToolUse]]
   [[hooks.PreToolUse.hooks]]
   type = "command"
   command = "python3 .agent-guard/guard_destructive.py --format codex"
   ```
3. `.codex/rules/default.rules` を作る（`codex execpolicy check --pretty --rules .codex/rules/default.rules -- rm -r results` で確認）:
   ```python
   prefix_rule(pattern = ["rm", ["-r", "-R", "-rf", "-fr", "-f"]], decision = "forbidden", justification = "再帰・強制削除は禁止")
   prefix_rule(pattern = ["rm"], decision = "prompt", justification = "削除は確認")
   prefix_rule(pattern = [["rmdir", "unlink", "mv", "chmod"]], decision = "prompt", justification = "削除・移動は確認")
   prefix_rule(pattern = [["shred", "dd", "mkfs", "sudo", "ssh", "scp"]], decision = "forbidden", justification = "破壊的操作・外部接続")
   prefix_rule(pattern = ["git", "reset", "--hard"], decision = "forbidden", justification = "変更が消える")
   prefix_rule(pattern = ["git", "clean"], decision = "forbidden", justification = "未追跡ファイルが消える")
   prefix_rule(pattern = ["git", ["push", "checkout", "restore", "rebase"]], decision = "prompt", justification = "確認")
   prefix_rule(pattern = [["curl", "wget"]], decision = "prompt", justification = "通信は確認")
   prefix_rule(pattern = [["pip", "pip3", "conda", "uv", "brew"]], decision = "prompt", justification = "インストールは確認")
   ```
4. `codex` を起動し、**「このフォルダを信頼するか」で信頼する**（しないと `.codex/` が読まれない）。`/status` で設定を確認。

注意: `workspace-write` ではフォルダ内のコマンドが確認なしで動くことがあるため、規則・フック・`chmod` がより重要です。
`--yolo` は使わないでください。規則は公式に「実験的」、フックは新しい機能なので、必ずテストしてください。
</details>

<details><summary>Cursor</summary>

`.cursor/hooks.json` を作り、設定画面でコマンドの自動実行を切って、拒否リストに `rm`, `mv`, `git reset`, `git clean`, `sudo` を入れます。
```json
{ "version": 1, "hooks": { "beforeShellExecution": [ { "command": "python3 .agent-guard/guard_destructive.py --format cursor" } ] } }
```
Cursor ではフックの「確認」が無視されるという報告があるため、ガードは確認すべき操作も**禁止**にします。
</details>

<details><summary>その他のエージェント（Copilot、Gemini 系、Cline など）を使う前のチェックリスト</summary>

1. フォルダの外に書き込めないようにできるか（サンドボックス）
2. コマンドやファイル編集の前に毎回確認させられるか
3. 特定のコマンドを禁止できるか（規則・拒否リスト・フック）。フックがあれば `guard_destructive.py` を呼ぶ（形式が違えば `respond()` に追加）
4. ネットワークを止められるか
5. 全自動モードを使わずに済むか
6. 入力データの扱いが所属機関の規定に合うか

できない項目があれば、読むだけの用途に限るか、①OS の読み取り専用・②git・③バックアップで守ってください。
</details>
