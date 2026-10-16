# -*- coding: utf-8 -*-
"""一键发布: 扫描蒸馏工作区 → 同步成品页到 content/ → 更新 library.json + 封面 → git commit/push

用法:
  python publish.py sync            # 同步全部新增/变更页并推送
  python publish.py sync --dry-run  # 只看会做什么, 不写盘不提交
  python publish.py sync --no-push  # 同步并提交, 但不 push

类型推断: series.json → videos; distill.json 里 source_type=person_topic 或
render_profile.archetype=人物 → biographies; 其余有 distill.json 的 → books;
都没有 → 跳过并提示。判错或判不出可用 --type books|videos|biographies 覆盖。
工作区路径在 publish_config.json 配置。仅标准库 + PIL(封面缩略图, 缺失则跳过缩略图)。
"""
import base64, io, json, re, shutil, subprocess, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
sys.stdout.reconfigure(encoding="utf-8")
CFG = json.loads((ROOT / "publish_config.json").read_text(encoding="utf-8"))
WORKSHOP = Path(CFG["workshop"])
DATA = WORKSHOP / "distill-data"
DRY = "--dry-run" in sys.argv
PUSH = "--no-push" not in sys.argv
# --type <books|videos|biographies>: 强制指定类型, 覆盖自动判型(判定见 infer_type)
TYPE_OVERRIDE = (sys.argv[sys.argv.index("--type") + 1]
                 if "--type" in sys.argv and len(sys.argv) > sys.argv.index("--type") + 1 else None)


def infer_type(d: Path):
    """按页面自己的数据判型, 判不出来返回 None(调用方报 SKIP)。

    只看"有没有 distill.json"是不够的: 人物页也有 distill.json, 会被判成 books。
    再用 distill.json 里的 source_type / render_profile.archetype 分书与人物。
    """
    if (d / "series.json").is_file():
        return "videos"
    dj = d / "distill.json"
    if dj.is_file():
        try:
            meta = json.loads(dj.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        if isinstance(meta, dict) and (
                meta.get("source_type") == "person_topic"
                or (meta.get("render_profile") or {}).get("archetype") == "人物"
                or meta.get("book_type") == "人物专题"):
            return "biographies"
        return "books"
    return None


def sh(*args):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", cwd=ROOT)


def meta_from_distill(slug: str, d: dict, html: str) -> dict:
    m = re.search(r'<p class="cb-kicker">(.*?)</p>', html)
    chars = sum(len(re.sub(r"\s+", "", c.get("narrative", ""))) for c in d.get("chapters", []))
    review_note = ""
    rf = DATA / slug / "reader-review.json"
    if rf.exists():
        schema = json.loads(rf.read_text(encoding="utf-8")).get("schema")
        review_note = "一轮内容审阅" if schema == "reader-review-v2" else (
            "production" if schema == "reader-production-v1" else "")
    return {
        "slug": slug,
        "type": None,  # 由调用方定
        "title": d.get("title", slug),
        "author": d.get("author", ""),
        "kicker": m.group(1) if m else d.get("book_type", ""),
        "slogan": d.get("hero_slogan", ""),
        "question": d.get("core_question", ""),
        "formula": (d.get("napkin") or {}).get("formula", ""),
        "chars": chars,
        "units": len(d.get("chapters", [])),
        "review_note": review_note,
        "path": None,
        "cover": None,
        "pub_year": d.get("pub_year"),
        "updated": date.today().isoformat(),
    }


def make_cover_thumb(slug: str) -> bool:
    src = DATA / slug / "_cover_data.txt"
    if not src.exists():
        return False
    try:
        from PIL import Image
    except ImportError:
        print(f"  ! 无 PIL, 跳过 {slug} 封面缩略图")
        return False
    raw = base64.b64decode(src.read_text("ascii").strip().split(",", 1)[1])
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    r = 300 / im.width
    im = im.resize((300, round(im.height * r)), Image.LANCZOS)
    out = ROOT / "assets" / "covers" / f"{slug}.jpg"
    if not DRY:
        im.save(out, "JPEG", quality=78, optimize=True)
    return True


def sync():
    if not DATA.is_dir():
        print(f"FAIL 工作区不存在: {DATA} (检查 publish_config.json)")
        return 1
    lib = json.loads((ROOT / "library.json").read_text(encoding="utf-8"))
    by_slug = {it["slug"]: it for it in lib}
    added, changed, skipped = [], [], []

    for d in sorted(DATA.iterdir()):
        slug = d.name
        page = d / f"{slug}.html"
        if not page.is_file():
            continue
        ptype = TYPE_OVERRIDE or infer_type(d)
        if ptype is None:
            skipped.append(f"{slug} (无法判断类型, 用 --type books|videos|biographies 指定)")
            continue
        if ptype not in ("books", "videos", "biographies"):
            print(f"FAIL --type 只认 books|videos|biographies, 收到 {ptype!r}")
            return 1

        dst = ROOT / "content" / ptype / f"{slug}.html"
        rel = f"content/{ptype}/{slug}.html"
        is_new = not dst.exists()
        is_diff = (not is_new) and dst.read_bytes() != page.read_bytes()
        if not (is_new or is_diff):
            continue

        html = page.read_text(encoding="utf-8")
        meta = {}
        distill_file = d / "distill.json"
        if distill_file.is_file():
            meta = meta_from_distill(slug, json.loads(distill_file.read_text(encoding="utf-8")), html)
        else:  # 视频等无 distill.json: 从 HTML 提取最低限度字段
            t = re.search(r"<title>(.*?)</title>", html)
            meta = {"slug": slug, "title": (t.group(1).split("·")[0].strip() if t else slug),
                    "author": "", "kicker": "视频系列", "slogan": "", "question": "",
                    "pub_year": None, "review_note": "", "updated": date.today().isoformat()}
        meta["type"] = ptype
        meta["path"] = f"{ptype}/{slug}.html"
        if ptype == "videos":  # 书脊/列表展示集数(build_index.spine_meta 消费)
            try:
                meta["episodes"] = len(json.loads((d / "series.json").read_text(encoding="utf-8"))["videos"])
            except Exception:
                meta["episodes"] = len(json.loads(distill_file.read_text(encoding="utf-8")).get("videos", [])) if distill_file.is_file() else None
        has_cover = make_cover_thumb(slug)
        meta["cover"] = f"assets/covers/{slug}.jpg" if has_cover else None

        old = by_slug.get(slug)
        if old:  # 保留清单里的手工补充字段
            merged = {**meta, **{k: v for k, v in old.items() if k in ("review_note",) and v and not meta.get(k)}}
            for k, v in old.items():
                if k not in ("updated",) and k not in meta:
                    merged[k] = v
            meta = merged
        if not DRY:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(page, dst)
            lib = [it for it in lib if it["slug"] != slug] + [meta]
            json.dump(lib, open(ROOT / "library.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        (added if is_new else changed).append(f"{slug} → {rel}")

    for msg in skipped:
        print("SKIP", msg)
    if not added and not changed:
        print("已是最新, 无需同步")
        return 0
    for s in added:
        print("ADD ", s)
    for s in changed:
        print("UPD ", s)
    if DRY:
        print("(dry-run, 未写盘)")
        return 0

    # 提交
    sh("git", "add", "-A", "content", "assets", "library.json")
    msg = "publish: " + ", ".join([f"+{s.split(' ')[0]}" for s in added] + [f"~{s.split(' ')[0]}" for s in changed])
    r = sh("git", "commit", "-m", msg)
    if r.returncode != 0:
        print("FAIL git commit:", (r.stderr or r.stdout).strip()[:200])
        return 1
    print("COMMIT", msg)
    if PUSH:
        remote = sh("git", "remote")
        if not remote.stdout.strip():
            print("! 未配置 remote, 已提交未推送。git remote add origin <url> 后手动 push")
            return 0
        r = sh("git", "push")
        if r.returncode != 0:
            print("FAIL git push:", (r.stderr or r.stdout).strip()[:300])
            return 1
        print("PUSH 完成 -- GitHub Actions 将自动重建首页并部署")
    else:
        print("(--no-push, 已提交未推送)")
    return 0


if __name__ == "__main__":
    sys.exit(sync())
