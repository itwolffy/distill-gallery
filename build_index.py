# -*- coding: utf-8 -*-
"""构建首页: library.json + templates/index_template.html → dist/
- 校验清单引用的页面/封面真实存在, 失配即失败(不静默漏书)
- dist/ = index.html + content/ + assets/ (构建产物, 不入 git, CI 部署)
仅用标准库。
"""
import json, math, re, shutil, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
sys.stdout.reconfigure(encoding="utf-8")

TYPE_NAMES = {"books": "书", "videos": "视频", "biographies": "人物"}


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def build() -> int:
    lib = json.loads((ROOT / "library.json").read_text(encoding="utf-8"))
    tpl = (ROOT / "templates" / "index_template.html").read_text(encoding="utf-8")

    errs = []
    for it in lib:
        if not (ROOT / "content" / it["path"]).is_file():
            errs.append(f"[lib] {it['slug']}: content/{it['path']} 不存在")
        if it.get("cover") and not (ROOT / it["cover"]).is_file():
            errs.append(f"[lib] {it['slug']}: {it['cover']} 不存在")
        if it["type"] not in TYPE_NAMES:
            errs.append(f"[lib] {it['slug']}: 未知类型 {it['type']}")
    slugs = [it["slug"] for it in lib]
    if len(slugs) != len(set(slugs)):
        errs.append("[lib] 存在重复 slug")
    if errs:
        for e in errs:
            print("FAIL", e)
        return 1

    # 磁盘上有页、清单没登记 → 报错(防静默漏书)
    on_disk = {str(p.relative_to(ROOT / "content")).replace("\\", "/")
               for p in (ROOT / "content").rglob("*.html") if p.name != "index.html"}
    listed = {it["path"] for it in lib}
    if on_disk - listed:
        print("FAIL content/ 里有页面未登记进 library.json:", sorted(on_disk - listed))
        return 1

    lib.sort(key=lambda x: (x["type"], x.get("updated", ""), x["slug"]))
    total = len(lib)
    total_chars = sum(i.get("chars", 0) for i in lib)
    total_units = sum(i.get("units", 0) for i in lib)
    latest = max(i.get("updated", "") for i in lib)

    # 报头一行真实数据
    # 介质中性口径: 库里混了书/视频/人物, "本"与"阅读单元"都不成立
    stat_line = (f"{total} 份 · {round(total_chars/10000, 1)} 万字转述 · "
                 f"{total_units} 个单元 · 更新 {latest}")

    TYPE_VAR = {"books": "var(--green)", "videos": "var(--blue)", "biographies": "var(--red)"}

    # 书脊: 高度按转述字数线性映射(2万→160px, 4万→280px), 主题无关(用 token 换肤)
    def spine_h(chars: int) -> int:
        return int(max(160, min(290, 160 + (chars - 20000) * 0.006)))

    # 竖排版式实测常数(templates/index_template.html 的 .spine .t:15px / letter-spacing .24em)
    CHAR_H = 18.6        # 竖排一个字占的高度
    NARROW_H = 8.7       # 「·」这类窄字符
    COL_W = 15           # 每列占的宽度(= line-height)
    TITLE_TOP = 11       # .t 的 margin-top
    TITLE_GAP = 8        # 标题与下方字数之间的最小间距
    META_CH = 9          # 竖排 12px 字数每字占高
    BOTTOM_PAD = 11      # .spine 的 padding-bottom
    ONE_COL_SLACK = 24   # 单列放不下时, 允许比正文量高度高出这么多仍不拆列(拆列会难看不值)
    NARROW = "·．.、-"

    def label_h(label: str) -> float:
        return sum(NARROW_H if ch in NARROW else CHAR_H for ch in label)

    def cap_h(t: str) -> int:
        return {"videos": 15, "biographies": 9}.get(t, 6)

    def need_h(t: str, label: str, meta: str, cols: int) -> float:
        per = label_h(label) / max(1, len(label)) * math.ceil(len(label) / cols)
        return cap_h(t) + TITLE_TOP + per + TITLE_GAP + len(meta) * META_CH + BOTTOM_PAD

    def spine_label(it) -> str:
        """书脊短名。library.json 给了 spine_label 就用它(标题长的必备, 否则脊高被标题撑起来,
        和「脊高 = 转述正文量」的口径打架); 没给就按老规则自动取: 去括号内容、截到首个冒号/破折号段、封顶。"""
        if it.get("spine_label"):
            return it["spine_label"]
        s = re.sub(r"[（(【\[][^）)】\]]*[）)】\]]", "", it["title"]).strip()
        s = re.split(r"[：:—–]", s)[0].strip()
        return s if len(s) <= 10 else s[:10] + "…"

    def spine_meta(it) -> str:
        """脊上第二行: 给出该介质最有信息量的量; 缺字段则退回转述字数(高度口径始终是转述正文量)"""
        if it["type"] == "videos" and it.get("episodes"):
            return f"{it['episodes']} 集"
        if it["type"] == "biographies" and it.get("life_span"):
            return str(it["life_span"])
        return f"{round(it.get('chars', 0)/10000, 1)}万字"

    spines = []
    for it in lib:
        label = spine_label(it)
        meta = spine_meta(it)
        t = it["type"]
        base_w = 70 if t == "videos" else 54
        h0 = spine_h(it.get("chars", 20000))
        # 脊名尽量一列; 一列放不下(比正文量高度高出超过 ONE_COL_SLACK)就折两列, 再不够折三列。
        # 拆列时脊宽按列数加宽(每列 COL_W), 高度仍以正文量高度为底, 不被标题顶起来。
        cols = 1
        while cols < 3 and need_h(t, label, meta, cols) > h0 + ONE_COL_SLACK:
            cols += 1
        need = need_h(t, label, meta, cols)
        h = max(h0, round(need))
        w = base_w + (cols - 1) * COL_W
        # 交给浏览器在同样的高度里折列, 与上面的算式一致
        tmax = h - (cap_h(t) + TITLE_TOP + TITLE_GAP + len(meta) * META_CH + BOTTOM_PAD) + 6
        verb = "观看" if t == "videos" else "阅读"
        spines.append(
            f'      <a class="spine" data-type="{esc(t)}" '
            f'style="--h:{h}px;--sp:{TYPE_VAR[t]};--w:{w}px" '
            f'href="{esc(it["path"])}" aria-label="《{esc(it["title"])}》，{verb}" title="{esc(it["title"])}">'
            f'<span class="t" style="max-height:{max(0, tmax)}px">{esc(label)}</span>'
            f'<span class="len">{esc(meta)}</span></a>')

    counts = {t: sum(1 for i in lib if i["type"] == t) for t in TYPE_NAMES if any(i["type"] == t for i in lib)}
    chips = [f'<button class="chip on" data-type="all">全部<small>{total}</small></button>'] + [
        f'<button class="chip" data-type="{t}">{TYPE_NAMES[t]}<small>{n}</small></button>'
        for t, n in counts.items()]

    def render_formula(f: str) -> str:
        """配方里的运算符 = × ÷ + - 着色放大"""
        parts = re.split(r"([=×÷+])", f)
        return "".join(f'<span class="op">{esc(p)}</span>' if p in "=×÷+" else esc(p) for p in parts if p != "")

    cards = []
    for it in lib:
        unit_word = "个主题段" if it["type"] == "videos" else "个阅读单元"
        go_text = "阅读全文 →"   # 各介质统一(视频原先写「观看蒸馏页」, 改为与书/人物一致)
        year_word = f"发布 {it['pub_year']}" if (it.get("pub_year") and it["type"] == "videos") else (f"成书 {it['pub_year']}" if it.get("pub_year") else "")
        meta_bits = [f"{it.get('units', '-')} {unit_word}", f"约 {max(1, round(it.get('chars', 0)/400))} 分钟"]
        if it.get("review_note"):
            meta_bits.append(it["review_note"])
        if it.get("updated"):
            meta_bits.append(f"更新 {it['updated']}")
        dot = '<span class="dot">·</span>'
        byline = " · ".join(a for a in (it.get("author", ""), year_word) if a)
        has_eq = bool(it.get("formula"))
        cards.append(f'''    <article class="entry" data-type="{esc(it['type'])}">
      <a class="entry-link" style="--sp:{TYPE_VAR[it['type']]}" href="{esc(it['path'])}">
        <div class="entry-cover"><img src="{esc(it.get('cover') or '')}" alt="《{esc(it['title'])}》封面" width="300" height="460" loading="lazy" decoding="async"></div>
        <div class="entry-body">
          <p class="entry-kicker">{esc(it.get('kicker', ''))}</p>
          <h2 class="entry-title">{esc(it['title'])}</h2>
          <p class="entry-byline">{esc(byline)}</p>
          {f'<p class="eq"><span class="eq-t">{render_formula(it["formula"])}</span></p>' if has_eq else ''}
          <p class="entry-q">{esc(it.get('question', ''))}</p>
          <p class="entry-meta"><span>{dot.join(esc(b) for b in meta_bits)}</span><span class="go">{go_text}</span></p>
        </div>
      </a>
    </article>''')

    page = (tpl.replace("{{STAT}}", stat_line)
               .replace("{{SHELF}}", "\n".join(spines))
               .replace("{{FILTERS}}", " ".join(chips))
               .replace("{{CARDS}}", "\n".join(cards)))

    dist = ROOT / "dist"
    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir()
    # content/ 的子目录直接铺到 dist 根: content/books/x.html → dist/books/x.html
    # (library.json 的 path 是 books/x.html, 中间不能再夹一层 content)
    for sub in (ROOT / "content").iterdir():
        if sub.is_dir():
            shutil.copytree(sub, dist / sub.name)
        elif sub.suffix == ".html":
            shutil.copy2(sub, dist / sub.name)
    shutil.copytree(ROOT / "assets", dist / "assets")
    (dist / "index.html").write_text(page, encoding="utf-8")
    n = sum(1 for _ in dist.rglob("*") if _.is_file())
    print(f"OK dist/ 构建完成: {n} 个文件, 首页 {total} 个条目")
    return 0


if __name__ == "__main__":
    sys.exit(build())
