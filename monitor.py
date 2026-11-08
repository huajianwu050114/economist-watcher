"""Twice-weekly issue detector, optional authorized PDF downloader and notification.

Uses Python stdlib only. GitHub Actions persists small state in git; binary files
are kept out of git and made available as short-lived job artifacts by default.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from sources import Issue, USER_AGENT, load_issues

STATE_PATH = Path("data/seen.json")
DOWNLOAD_DIR = Path("downloads")
MAX_PDF_BYTES = 80 * 1024 * 1024


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_state(path: Path) -> dict:
    if not path.exists():
        return {"schema": 1, "seen": {}}
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("schema") != 1 or not isinstance(obj.get("seen"), dict):
        raise ValueError("Unsupported or malformed state file")
    return obj


def save_state(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def pdf_url_map() -> dict[str, str]:
    raw = os.getenv("PDF_URL_MAP_JSON", "").strip()
    if not raw:
        return {}
    obj = json.loads(raw)
    if not isinstance(obj, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in obj.items()):
        raise ValueError("PDF_URL_MAP_JSON must be an object mapping date/issue to HTTPS PDF URL")
    return obj


def authorized_pdf_link(issue: Issue, mapping: dict[str, str]) -> str | None:
    direct = mapping.get(issue.key) or mapping.get(issue.date)
    if direct:
        return direct
    template = os.getenv("PDF_URL_TEMPLATE", "").strip()
    if template:
        return template.replace("{date}", issue.date).replace("{edition}", issue.edition)
    return None


def download_pdf(url: str, issue: Issue, directory: Path = DOWNLOAD_DIR) -> tuple[str, str]:
    # No paywall bypass, browser automation, Telegram scraping or dynamic download endpoint support.
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only absolute HTTPS PDF URLs without embedded credentials are accepted")
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / f"The_Economist_{issue.date}_{issue.edition}.pdf"
    if dest.is_file():
        with dest.open("rb") as f:
            if f.read(5) == b"%PDF-":
                digest_existing = sha256()
                f.seek(0)
                for data in iter(lambda: f.read(64 * 1024), b""):
                    digest_existing.update(data)
                return dest.name, digest_existing.hexdigest()
    tmp = dest.with_suffix(".pdf.part")
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf"})
        digest = sha256()
        size = 0
        with urlopen(req, timeout=45) as res, tmp.open("wb") as f:
            if urlparse(res.geturl()).scheme != "https":
                raise ValueError("Redirect downgraded from HTTPS")
            while True:
                chunk = res.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_PDF_BYTES:
                    raise ValueError("PDF exceeds 80 MiB limit")
                digest.update(chunk)
                f.write(chunk)
        with tmp.open("rb") as f:
            signature = f.read(5)
        if size < 16 or signature != b"%PDF-":
            raise ValueError("Response is not a valid-looking PDF (may be HTML/login page)")
        tmp.replace(dest)
        return dest.name, digest.hexdigest()
    finally:
        if tmp.exists():
            tmp.unlink()


def _post_json(url: str, payload: dict, *, token: str | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, data=body, headers=headers, method="POST"), timeout=20) as res:
        return json.loads(res.read(128_000).decode("utf-8"))


def notify_github(issue: Issue) -> int | None:
    token, repo = os.getenv("GITHUB_TOKEN", ""), os.getenv("GITHUB_REPOSITORY", "")
    if not token or not repo:
        return None
    title = f"📰 新刊 · The Economist {issue.edition} · {issue.date}"
    body = f"发现新刊：[{issue.title}]({issue.link})\n\n出版日期：{issue.date}\n版本：{issue.edition}\n\n此通知仅包含索引信息，不附带未经授权的刊物文件。"
    result = _post_json(f"https://api.github.com/repos/{repo}/issues", {"title": title, "body": body, "labels": []}, token=token)
    return int(result["number"])


def notify_telegram(issue: Issue) -> bool:
    token, chat_id = os.getenv("TG_BOT_TOKEN", ""), os.getenv("TG_CHAT_ID", "")
    if not token or not chat_id:
        return False
    data = json.dumps({"chat_id": chat_id, "text": f"📰 新一期 The Economist\n{issue.title}\n{issue.link}"}).encode("utf-8")
    req = Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=20) as res:
        result = json.loads(res.read(128_000).decode("utf-8"))
    return result.get("ok") is True


def make_summary(issues: list[Issue], new: list[Issue], source: str, warnings: list[str], downloaded: list[str], *, initial: bool) -> str:
    lines = ["# The Economist · 更新监测", "", f"- 检查时间 (UTC)：{now()}", f"- 来源：{source}", f"- 本次扫描到：{len(issues)} 期", f"- 本次新增：{len(new)} 期", f"- PDF 成功获取：{len(downloaded)} 份", ""]
    if initial:
        lines += ["> 首次启动：自动记录历史条目，仅将最新一期标为新增，避免批量通知旧刊。", ""]
    if new:
        lines += ["## 新发现", ""]
        lines += [f"- [{i.title}]({i.link})" for i in new]
    else:
        lines += ["## 检查结果", "", "没有发现新的匹配刊物，已正常结束。"]
    if downloaded:
        lines += ["", "## 下载成功（本次运行的临时文件）", ""] + [f"- `{s}`" for s in downloaded]
    if warnings:
        lines += ["", "## 注意 / 待处理", ""] + [f"- {w}" for w in warnings]
    lines += ["", "说明：新刊监测不代表 PDF 下载成功；仅对配置的授权直链执行 PDF 下载。", ""]
    return "\n".join(lines)


def run(edition: str, fixture: str | None = None, *, quiet_first_run: bool = False, no_notify: bool = False, state_path: Path = STATE_PATH) -> int:
    # Parse secrets before changing the state: invalid config must fail fast.
    mapping = pdf_url_map()
    state = read_state(state_path)
    issues, source = load_issues(edition, fixture=fixture)
    first = len(state["seen"]) == 0
    missing = [i for i in issues if i.key not in state["seen"]]
    if first:
        selected = [] if quiet_first_run else missing[:1]  # issues sorted newest first
        ignored = {i.key for i in missing if i not in selected}
    else:
        selected, ignored = missing, set()

    for issue in missing:
        record = issue.as_dict()
        record["first_seen_at"] = now()
        record["notified_github_issue"] = None
        record["notified_telegram"] = False
        record["pdf_status"] = "unconfigured"
        record["initial_baseline"] = issue.key in ignored
        state["seen"][issue.key] = record

    warnings: list[str] = []
    downloaded: list[str] = []
    # Process previously discovered items too: if their authorized URL is supplied later,
    # the next run can retry without pretending they are brand new.
    for issue in issues:
        rec = state["seen"][issue.key]
        link = authorized_pdf_link(issue, mapping)
        if not link or rec.get("pdf_status") == "downloaded":
            continue
        try:
            filename, digest = download_pdf(link, issue)
            rec.update({"pdf_status": "downloaded", "pdf_file": filename, "pdf_sha256": digest})
            downloaded.append(filename)
        except Exception as exc:
            rec["pdf_status"] = "failed"
            warnings.append(f"授权 PDF {issue.date} 下载失败，下次会重试：{type(exc).__name__}: {exc}")

    if not no_notify:
        for issue in issues:
            rec = state["seen"][issue.key]
            if rec.get("initial_baseline"):
                continue
            if os.getenv("GITHUB_TOKEN") and os.getenv("GITHUB_REPOSITORY") and not rec.get("notified_github_issue"):
                try:
                    rec["notified_github_issue"] = notify_github(issue)
                except Exception as exc:
                    warnings.append(f"GitHub Issues 通知失败，下次重试 {issue.date}: {type(exc).__name__}: {exc}")
            if os.getenv("TG_BOT_TOKEN") and os.getenv("TG_CHAT_ID") and not rec.get("notified_telegram"):
                try:
                    rec["notified_telegram"] = notify_telegram(issue)
                except Exception as exc:
                    warnings.append(f"Telegram 通知失败，下次重试 {issue.date}: {type(exc).__name__}: {exc}")

    save_state(state_path, state)
    summary = make_summary(issues, selected, source, warnings, downloaded, initial=first)
    print(summary)
    out_file = os.getenv("GITHUB_STEP_SUMMARY", "")
    if out_file:
        with open(out_file, "a", encoding="utf-8") as out:
            out.write(summary + "\n")
    return 2 if any("下载失败" in w for w in warnings) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor new Economist issues (stdlib only)")
    parser.add_argument("--edition", choices=("asia", "uk", "usa", "europe", "middle-east-africa", "unspecified", "all"), default=os.getenv("EDITION", "asia"))
    parser.add_argument("--fixture", help="Offline fixture for testing (no network)")
    parser.add_argument("--quiet-first-run", action="store_true", help="Seed all current issues without initial notification")
    parser.add_argument("--no-notify", action="store_true")
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    args = parser.parse_args()
    try:
        return run(args.edition, args.fixture, quiet_first_run=args.quiet_first_run, no_notify=args.no_notify, state_path=args.state)
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
