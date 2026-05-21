# claude-status — a Claude Code statusline with a CodeNavi index badge (MIT).
# Full line (model · repo · context% · session time · t/s) plus a CodeNavi badge:
#   ✦ <codebase>  index coverage of the current repo (grey=covered, yellow=uncovered, red=server down)
#   🟢            prefix when a CodeNavi tool was used in the response to the current prompt
# Set CODENAVI_PORT / CODENAVI_HOST to point at a non-default server. CODENAVI_CODEBASE pins coverage.
import sys, json, os, urllib.request
from datetime import datetime, timezone


def fmt_k(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(n)


def fmt_dur(seconds: int) -> str:
    h, r = divmod(seconds, 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h}h:{m:02d}m"
    return f"{m}m:{s:02d}s"


def _seg_matches(seg, name):
    """A path segment maps to a codebase name (exact, or name + a -/_/. boundary)."""
    return seg == name or seg.startswith(name + "-") or seg.startswith(name + "_") or seg.startswith(name + ".")


def codenavi_status(repo, cwd="", url=None, timeout: float = 0.5):
    """Coverage of the current location by a local CodeNavi server.

    Returns (state, codebase_name):
      ("covered", name)   server up and the current repo/path maps to an indexed codebase
      ("uncovered", None) server up but nothing maps
      ("down", None)      server unreachable

    Matching is tiered, most reliable first, because the git folder name (e.g. an SVN
    'trunk' working copy) often differs from the indexed codebase name, and /health only
    reports container-internal paths so host paths can't be compared directly:
      0. CODENAVI_CODEBASE env override (exact escape hatch for ambiguous checkouts)
      1. exact match: git folder name == codebase name
      2. path-segment match below $HOME, shallowest segment wins, longer name breaks ties
         (handles e.g. .../myproject-checkout/trunk -> myproject; ignores the home/username dirs).
    """
    if url is None:
        host = os.environ.get("CODENAVI_HOST", "localhost")
        port = os.environ.get("CODENAVI_PORT", "8765")
        url = f"http://{host}:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
    except Exception:
        return ("down", None)
    codebases = list(data.get("codebases") or {})
    if not codebases:
        return ("uncovered", None)

    override = os.environ.get("CODENAVI_CODEBASE", "").strip().lower()
    if override:
        for name in codebases:
            if name.lower() == override:
                return ("covered", name)

    if repo:
        for name in codebases:
            if name.lower() == repo.lower():
                return ("covered", name)

    if cwd:
        norm = cwd.replace("\\", "/")
        home = os.path.expanduser("~").replace("\\", "/")
        rel = norm[len(home):] if home and norm.startswith(home) else norm
        segments = [s for s in rel.lower().split("/") if s]
        best = None  # (depth, name) — prefer shallowest, then longest name
        for depth, seg in enumerate(segments):
            for name in codebases:
                if _seg_matches(seg, name.lower()):
                    if best is None or depth < best[0] or (depth == best[0] and len(name) > len(best[1])):
                        best = (depth, name)
        if best:
            return ("covered", best[1])

    return ("uncovered", None)


def git_info(start: str) -> tuple[str, str] | None:
    d = os.path.abspath(start)
    while True:
        git_dir = os.path.join(d, ".git")
        _main_repo = None
        if os.path.isdir(git_dir):
            head_path = os.path.join(git_dir, "HEAD")
        elif os.path.isfile(git_dir):
            try:
                with open(git_dir, "r", encoding="utf-8") as f:
                    gd = f.read().strip()
                if gd.startswith("gitdir:"):
                    resolved = gd.split(":", 1)[1].strip()
                    if not os.path.isabs(resolved):
                        resolved = os.path.join(d, resolved)
                    head_path = os.path.join(resolved, "HEAD")
                    norm = resolved.replace("\\", "/")
                    idx = norm.find("/.git/")
                    _main_repo = norm[:idx].rsplit("/", 1)[-1] if idx != -1 else None
                else:
                    return None
            except Exception:
                return None
        else:
            parent = os.path.dirname(d)
            if parent == d:
                return None
            d = parent
            continue
        try:
            with open(head_path, "r", encoding="utf-8") as f:
                head = f.read().strip()
        except Exception:
            return None
        if head.startswith("ref: "):
            ref = head[5:]
            branch = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref.rsplit("/", 1)[-1]
        else:
            branch = head[:7] if head else "?"
        worktree = os.path.basename(d)
        if _main_repo and _main_repo != worktree:
            return _main_repo, worktree
        return worktree, branch


def response_tps(entries):
    """Tokens/sec of the LAST assistant response.

    A single response is logged as several transcript entries that share one
    requestId and repeat the SAME cumulative output_tokens. Measure tokens over the
    response's whole wall-clock span (the entry that triggered it -> its last entry);
    never divide the cumulative count by the gap between two sub-entries of the same
    response (that yields absurd rates like 40000 t/s).
    """
    prev_ts = None
    prev_type = None
    last_rid = None
    start_ts = end_ts = None
    out = 0
    for d in entries:
        ts = d.get("timestamp")
        typ = d.get("type")
        if typ == "assistant":
            rid = d.get("requestId")
            o = ((d.get("message") or {}).get("usage") or {}).get("output_tokens", 0) or 0
            if prev_type != "assistant" or rid != last_rid:   # a new response begins
                start_ts, out, end_ts = prev_ts, o, ts
            else:                                              # continuation of the same response
                out = max(out, o)
                if ts:
                    end_ts = ts
            last_rid = rid
        if ts:
            prev_ts = ts
        prev_type = typ
    if not (start_ts and end_ts) or out < 20:
        return None
    try:
        dur = (datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
               - datetime.fromisoformat(start_ts.replace("Z", "+00:00"))).total_seconds()
    except Exception:
        return None
    if dur < 1.0:
        return None
    rate = out / dur
    return rate if rate <= 1000 else None  # defensive: implausible -> hide rather than show garbage


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        payload = {}

    model_full = (payload.get("model") or {}).get("display_name") or "?"
    model = model_full.split(" (", 1)[0].strip()
    cwd = payload.get("cwd") or (payload.get("workspace") or {}).get("current_dir") or ""
    transcript_path = payload.get("transcript_path")

    last_input = 0
    last_cache_r = 0
    last_cache_c = 0
    first_ts: str | None = None
    rag_used = False  # was a CodeNavi tool used in the response to the latest human prompt?

    entries = []
    if transcript_path and os.path.isfile(transcript_path):
        try:
            with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            entries = []

    for d in entries:
        ts = d.get("timestamp")
        if ts and first_ts is None:
            first_ts = ts
        typ = d.get("type")
        content = (d.get("message") or {}).get("content")
        if typ == "user":
            # A genuine human prompt (not a tool_result echo) starts a new turn.
            is_tool_result = isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            )
            if not is_tool_result:
                rag_used = False
        if typ == "assistant":
            usage = (d.get("message") or {}).get("usage") or {}
            if usage.get("input_tokens") is not None:
                last_input = usage["input_tokens"]
            if usage.get("cache_read_input_tokens") is not None:
                last_cache_r = usage["cache_read_input_tokens"]
            if usage.get("cache_creation_input_tokens") is not None:
                last_cache_c = usage["cache_creation_input_tokens"]
            if isinstance(content, list):
                for b in content:
                    if (isinstance(b, dict) and b.get("type") == "tool_use"
                            and "codenavi" in str(b.get("name", "")).lower()):
                        rag_used = True

    context_used = last_input + last_cache_r + last_cache_c

    if "1m" in model_full.lower():
        max_ctx = 1_000_000
    else:
        max_ctx = 200_000
    pct = (context_used / max_ctx * 100) if max_ctx else 0

    elapsed = ""
    if first_ts:
        try:
            start = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
            secs = int((datetime.now(timezone.utc) - start).total_seconds())
            elapsed = fmt_dur(secs)
        except Exception:
            pass

    tps = response_tps(entries)

    DIM = "\x1b[2m"
    CYAN = "\x1b[36m"
    YELLOW = "\x1b[33m"
    GREEN = "\x1b[32m"
    RED = "\x1b[31m"
    ORANGE = "\x1b[38;5;208m"
    GREY = "\x1b[90m"
    RESET = "\x1b[0m"
    SEP = f"{DIM} | {RESET}"

    parts = [
        f"{CYAN}{model}{RESET}",
    ]
    gi = git_info(cwd) if cwd else None
    if gi:
        repo, branch = gi
        parts.append(f"{YELLOW}{repo}@{branch}{RESET}")
    ctx_color = RED if pct >= 50 else GREY
    parts.append(f"{ctx_color}{fmt_k(context_used)} /{fmt_k(max_ctx)} ~ {pct:.0f}%{RESET}")
    if elapsed:
        parts.append(f"{ORANGE}{elapsed}{RESET}")
    cn_state, cn_name = codenavi_status(gi[0] if gi else None, cwd)
    rag_glyph = "🟢 " if rag_used else ""
    if cn_state == "covered":
        parts.append(f"{rag_glyph}{GREY}✦ {cn_name}{RESET}")
    elif cn_state == "uncovered":
        parts.append(f"{rag_glyph}{YELLOW}✦ uncovered{RESET}")
    else:
        parts.append(f"{rag_glyph}{RED}✦ ✗{RESET}")
    if tps is not None:
        parts.append(f"{DIM}{tps:.1f} t/s{RESET}")

    print(SEP.join(parts))


if __name__ == "__main__":
    main()
