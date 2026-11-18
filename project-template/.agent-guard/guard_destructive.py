#!/usr/bin/env python3
"""コーディングエージェント共通の「削除・上書きガード」フック。

エージェントが実行しようとするシェルコマンドを検査し、
ファイル削除・上書き・履歴破棄につながる操作を止める（deny）か、
人間の確認を求める（ask）。

使い方（エージェントごとに --format を変える。詳細は PORTING.md）:
    python3 .agent-guard/guard_destructive.py --format claude   # Claude Code（PreToolUse）
    python3 .agent-guard/guard_destructive.py --format codex    # OpenAI Codex（PreToolUse）
    python3 .agent-guard/guard_destructive.py --format cursor   # Cursor（beforeShellExecution）
    python3 .agent-guard/guard_destructive.py --format gemini   # Gemini 系 CLI（BeforeTool）
    python3 .agent-guard/guard_destructive.py --check "rm -r results"   # 手動テスト

エージェントの権限ルールは多くが「コマンドの先頭一致」なので、
`cd x && rm -r y` や `python -c "shutil.rmtree(...)"` のような書き方をすり抜けることがある。
このフックはコマンド全体を正規表現で調べ、その穴を補う。

限界: `python analyze.py` のように、スクリプトファイルの中で削除する処理は検出できない。
最終的な防御は「生データを読み取り専用にする」「バックアップ / git を使う」こと（README 参照）。

依存: Python 3 標準ライブラリのみ。
"""
import argparse
import json
import re
import sys

# 生データフォルダ（AGENTS.md の構成と合わせる）
RAW_DIR = r"data/raw"

# --- 必ず止める（Claude は実行できない。必要なら人間が自分の端末で実行する） ---
DENY = [
    (r"\brm\s+(-\S*[rRf]\S*|--recursive|--force)", "rm の再帰削除 / 強制削除"),
    (r"\bfind\b.*\s-delete\b", "find -delete による一括削除"),
    (r"\bfind\b.*-exec\s+rm\b", "find -exec rm による一括削除"),
    (r"\bxargs\b.*\brm\b", "xargs rm による一括削除"),
    (r"\brsync\b.*--delete", "rsync --delete（同期先のファイル削除）"),
    (r"\bshred\b", "shred（復元不能な削除）"),
    (r"\bdd\b\s+.*\bof=", "dd による書き込み"),
    (r"\bmkfs\b|\bdiskutil\s+(erase|partition|reformat)", "ディスクの初期化"),
    (r"\bgit\s+clean\b.*\s-\S*f", "git clean -f（未追跡ファイルの削除）"),
    (r"\bgit\s+reset\s+.*--hard|\bgit\s+reset\s+--hard", "git reset --hard（変更の破棄）"),
    (r"\bgit\s+push\b.*(\s--force\b|\s-f\b|--force-with-lease)", "git push --force（履歴の上書き）"),
    (r"\bsudo\b", "sudo（管理者権限）"),
]

# --- 確認を求める（毎回 人間が内容を見て許可/拒否する） ---
ASK = [
    (r"(^|[;&|(\s])rm\s", "ファイル削除 (rm)"),
    (r"\brmdir\b|\bunlink\b", "削除 (rmdir / unlink)"),
    (r"(^|[;&|(\s])mv\s", "移動 / 名前変更 (mv) — 移動先に同名ファイルがあると上書きされる"),
    (r"\bgit\s+(checkout|restore)\b.*(\s--\s|\s\.(\s|$))", "git checkout/restore による未コミット変更の破棄"),
    (r"\btruncate\b", "truncate（ファイル内容の切り詰め）"),
    (r"shutil\.rmtree|shutil\.move|os\.remove|os\.unlink|os\.rmdir|\.unlink\(|\.rmdir\(|send2trash",
     "Python ワンライナー内の削除 / 移動"),
    (r"unlink\(|file\.remove\(|fs\.rm", "スクリプト内の削除処理"),
]

# 生データに触れる書き込み系の操作は止める（data/raw から「読む・コピーして持ち出す」のは可）
RAW_WRITE = re.compile(
    r"(\brm\b|\bmv\b|\bsed\s+-i|\btee\b|\btouch\b|\bchmod\b|\btruncate\b|>>?)\s*[^;&|]*" + re.escape(RAW_DIR)
)
# cp / rsync / ln は「コピー先（最後の引数）が data/raw」の場合だけ止める
RAW_COPY_INTO = re.compile(
    r"\b(cp|rsync|ln|install)\b[^;&|]*\s\S*" + re.escape(RAW_DIR) + r"\S*\s*($|[;&|])"
)


# ---------------------------------------------------------------------------
# 判定（エージェントに依存しない部分）
# ---------------------------------------------------------------------------
def decide(cmd):
    """Return (decision, reason). decision is "deny", "ask", or None (= 通す)."""
    if RAW_WRITE.search(cmd) or RAW_COPY_INTO.search(cmd):
        return "deny", (f"[guard] 生データ ({RAW_DIR}) への書き込み・削除・移動は禁止されています。"
                        " 処理結果は data/processed/ か results/ に保存してください。")
    for pat, label in DENY:
        if re.search(pat, cmd):
            return "deny", (f"[guard] 禁止操作: {label}。"
                            " 本当に必要なら、エージェントに実行させず研究者が自分の端末で実行してください。")
    for pat, label in ASK:
        if re.search(pat, cmd):
            return "ask", f"[guard] 要確認: {label}。対象ファイルを確認してから許可してください。"
    return None, ""


def extract_command(payload):
    """各エージェントの入力 JSON からシェルコマンド文字列を取り出す。"""
    if isinstance(payload.get("command"), str):          # Cursor beforeShellExecution
        return payload["command"]
    ti = payload.get("tool_input") or payload.get("toolInput") or {}
    if isinstance(ti, str):
        return ti
    for key in ("command", "cmd", "script"):
        v = ti.get(key)
        if isinstance(v, str):
            return v
        if isinstance(v, list):                         # ["bash", "-lc", "rm -r x"] 形式
            return " ".join(str(x) for x in v)
    return ""


# ---------------------------------------------------------------------------
# 出力（エージェントごとの形式）
# ---------------------------------------------------------------------------
def respond(fmt, decision, reason):
    if decision is None:
        return 0
    print(reason, file=sys.stderr)
    if fmt in ("claude", "codex"):
        # Claude Code と Codex は同じ PreToolUse 形式（Codex 側の対応は要確認: PORTING.md）
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }}, ensure_ascii=False))
        return 0
    if fmt == "cursor":
        # Cursor では "ask" が無視されるという報告があるため、ask も deny として扱う
        print(json.dumps({"permission": "deny", "userMessage": reason, "agentMessage": reason},
                         ensure_ascii=False))
        return 0
    if fmt == "gemini":
        # Gemini 系: decision=deny、または exit code 2 + stderr でブロック
        print(json.dumps({"decision": "deny", "reason": reason}, ensure_ascii=False))
        return 2
    return 2  # 未知の形式: 安全側（exit 2 は多くのエージェントで「ブロック」）


def main():
    ap = argparse.ArgumentParser(description="削除・上書きガード")
    ap.add_argument("--format", default="claude", choices=["claude", "codex", "cursor", "gemini"])
    ap.add_argument("--check", metavar="COMMAND", help="コマンド文字列を判定して表示（手動テスト用）")
    args = ap.parse_args()

    if args.check is not None:
        d, r = decide(args.check)
        print(f"{d or 'pass':5}  {args.check}" + (f"\n       {r}" if r else ""))
        return 0

    fmt = args.format
    try:
        payload = json.load(sys.stdin)
        cmd = extract_command(payload)
        if not cmd:
            return 0
        d, r = decide(cmd)
    except Exception as e:  # 検査に失敗したら黙って通さない
        d, r = ("ask" if fmt in ("claude", "codex") else "deny"), f"[guard] コマンド検査に失敗しました ({e})。"
    return respond(fmt, d, r)


if __name__ == "__main__":
    sys.exit(main())
