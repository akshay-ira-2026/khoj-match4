#!/usr/bin/env python3
"""Khoj: exact-answer web retrieval agent (AMD AI League Match 4).

Contract: one query per process. Query comes from argv (--query/--url/--id),
env (QUERY, START_URL, QUERY_ID) or /app/input/*.json ({id, query, url}).
Writes /app/output/<id>_output.json with answer, citations, sources,
source_url, confidence. A placeholder is written first so a timeout never
leaves no file. No API keys: optional local Qwen via transformers, else rules.
"""
import argparse, glob, html, json, os, re, sys, time, urllib.parse, urllib.request
from html.parser import HTMLParser

DEADLINE = float(os.environ.get("KHOJ_DEADLINE", "24"))
T0 = time.time()
OUT_DIR = os.environ.get("OUTPUT_DIR", "/app/output")
UA = "Mozilla/5.0 (X11; Linux x86_64) KhojAgent/1.0"

def left():
    return DEADLINE - (time.time() - T0)

# ---------- page reading ----------
class Reader(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}
    BLOCK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "br", "section", "article", "table", "dd", "dt"}
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.skip, self.parts, self.links, self.a, self.atext = base, 0, [], [], None, []
        self.cells = []
    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP: self.skip += 1
        if tag in self.BLOCK: self.parts.append("\n")
        if tag in ("td", "th"): self.parts.append(" | ")
        if tag == "a":
            href = dict(attrs).get("href")
            if href and not href.startswith(("#", "javascript:", "mailto:")):
                self.a, self.atext = urllib.parse.urljoin(self.base, href), []
    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip: self.skip -= 1
        if tag == "a" and self.a:
            self.links.append((self.a, " ".join(self.atext).strip())); self.a = None
    def handle_data(self, d):
        if self.skip: return
        self.parts.append(d)
        if self.a: self.atext.append(d.strip())
    def text(self):
        t = "".join(self.parts)
        lines = [re.sub(r"[ \t\xa0]+", " ", l).strip(" |") for l in t.split("\n")]
        return "\n".join(l for l in lines if l)

def fetch(url, timeout=6):
    if url.startswith("file://") or os.path.exists(url):
        p = url[7:] if url.startswith("file://") else url
        return open(p, encoding="utf-8", errors="ignore").read(), "file://" + os.path.abspath(p)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=max(1, min(timeout, left() - 2))) as r:
        return r.read(2_000_000).decode(r.headers.get_content_charset() or "utf-8", "ignore"), r.geturl()

def read_page(url):
    raw, final = fetch(url)
    rd = Reader(final); rd.feed(raw)
    return rd.text(), rd.links, final

def search(query):
    """Keyless search: DuckDuckGo html endpoint. Returns result URLs."""
    try:
        raw, _ = fetch("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query), 6)
    except Exception:
        return []
    urls = []
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"', raw):
        u = html.unescape(m.group(1))
        q = urllib.parse.parse_qs(urllib.parse.urlparse(u).query).get("uddg")
        urls.append(q[0] if q else u)
    return urls[:5]

# ---------- question understanding ----------
STOP = set("what is the of a an in on for to and or how many much which who when where does do did was were are by with from at as that this its it be please tell me find give".split())
def terms(q):
    ql = re.sub(r"e-mail", "email", q.lower())
    return [w.strip(".-") for w in re.findall(r"[a-z0-9][a-z0-9.\-]*", ql) if w not in STOP and len(w) > 1]

# words a link to the right page usually carries, by answer type
HINTS = {
    "price": ["pricing", "price", "plans", "buy", "shop"],
    "version": ["release", "changelog", "version", "download", "news"],
    "phone": ["contact", "support", "help", "about"],
    "email": ["contact", "support", "help", "about"],
    "name": ["about", "team", "leadership", "people", "company"],
    "date": ["about", "history", "news", "release", "company"],
    "number": ["about", "stats", "facts", "data"],
    "text": ["about", "faq", "docs"],
}

def answer_type(q):
    ql = q.lower()
    if re.search(r"\bprice|cost|how much\b|fee|\$|₹|usd|inr", ql): return "price"
    if re.search(r"\bwhen\b|date|year|released on|founded|launched", ql): return "date"
    if re.search(r"\bversion|release\b", ql): return "version"
    if re.search(r"phone|telephone|contact number", ql): return "phone"
    if re.search(r"e-?mail address", ql): return "email"
    if re.search(r"how many|number of|count|population|percentage|percent|%", ql): return "number"
    if re.search(r"\bwho\b|name of|ceo|founder|author", ql): return "name"
    return "text"

PAT = {
    "price": r"(?:[$€£₹]|USD|INR|Rs\.?)\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:/|per)\s?\w+)?|\d[\d,]*(?:\.\d+)?\s?(?:USD|INR|EUR|dollars|rupees)",
    "date": r"\b(?:\d{1,2}\s)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s(?:\d{1,2},?\s)?\d{4}\b|\b\d{4}-\d{2}-\d{2}\b|\b(?:19|20)\d{2}\b",
    "version": r"\bv?\d+\.\d+(?:\.\d+){0,2}(?:[-.]?(?:rc|beta|alpha)\d*)?\b",
    "phone": r"\+?\d[\d\s().-]{7,}\d",
    "email": r"[\w.+-]+@[\w-]+\.[\w.]+",
    "number": r"\b\d[\d,]*(?:\.\d+)?\s?(?:%|percent|million|billion|crore|lakh)?",
    "name": r"\b[A-Z][a-z]+(?:\s[A-Z][a-z.]+){1,3}\b",
}

def passages(text):
    lines = text.split("\n")
    for i, l in enumerate(lines):
        yield i, " ".join(lines[max(0, i - 1):i + 2]), l

def score(passage, ts):
    pl = passage.lower()
    return sum(2 if len(t) > 4 else 1 for t in ts if re.search(r"(?<![a-z0-9])" + re.escape(t), pl))

def candidates(text, q, url):
    ts, at = terms(q), answer_type(q)
    out = []
    for i, ctx, line in passages(text):
        s = 0.5 * score(ctx, ts) + 2 * score(line, ts)
        if s <= 0: continue
        if at == "text":
            out.append((s, line[:200], url, line)); continue
        for m in re.finditer(PAT[at], line):
            v = m.group(0).strip(" .,;")
            if at == "name" and v.lower() in " ".join(ts): continue
            # prefer the value closest to a query term on its line
            pos = min([abs(line.lower().find(t) - m.start()) for t in ts if t in line.lower()] or [99])
            out.append((s + 1.0 / (1 + pos / 20), v, url, line))
    return out

# ---------- optional local model ----------
_LLM = None
def llm_pick(q, cands):
    global _LLM
    if os.environ.get("KHOJ_LLM", "1") == "0" or left() < 8: return None
    try:
        if _LLM is None:
            from transformers import pipeline
            mid = os.environ.get("KHOJ_MODEL", "/app/models/qwen3-4b-instruct")
            if not os.path.isdir(mid): return None
            _LLM = pipeline("text-generation", model=mid, device_map="auto", torch_dtype="auto")
        ctx = "\n".join(f"[{i}] {c[3][:300]}" for i, c in enumerate(cands[:6]))
        msg = [{"role": "user", "content": f"Question: {q}\nPassages:\n{ctx}\nReply with only the exact answer value copied from a passage, then ' ||| ' and the passage number. If none answers it, reply NONE."}]
        o = _LLM(msg, max_new_tokens=48, do_sample=False)[0]["generated_text"][-1]["content"].strip()
        if o.upper().startswith("NONE"): return ("", None)
        val, _, idx = o.partition("|||")
        idx = int(re.sub(r"\D", "", idx) or 0)
        val = val.strip()
        if val and val.lower() in cands[idx][3].lower():
            return (val, cands[idx][2])
    except Exception:
        return None
    return None

# ---------- agent ----------
def run(qid, q, start):
    urls, seen, cands = ([start] if start else []), set(), []
    if not urls: urls = search(q)
    ts = terms(q)
    while urls and left() > 4 and len(seen) < 8:
        u = urls.pop(0)
        if u in seen: continue
        seen.add(u)
        try:
            text, links, final = read_page(u)
        except Exception:
            continue
        cands += candidates(text, q, final)
        # follow same-site links whose text matches the question
        host = urllib.parse.urlparse(final).netloc
        hints = HINTS.get(answer_type(q), [])
        ranked = sorted(((score(t + " " + l, ts) + 2 * score(t + " " + l, hints), l) for l, t in links
                        if urllib.parse.urlparse(l).netloc == host and l not in seen), reverse=True)
        urls += [l for s, l in ranked[:3] if s > 0]
    cands.sort(key=lambda c: -c[0])
    if not cands:
        return "", [], 0.0
    pick = llm_pick(q, cands)
    if pick and pick[0]:
        return pick[0], [pick[1]], 0.85
    if pick == ("", None):
        return "", [], 0.0
    best = cands[0]
    agree = sum(1 for c in cands[:5] if c[1].lower() == best[1].lower())
    conf = round(min(0.9, 0.35 + 0.1 * best[0] + 0.1 * agree), 2)
    return best[1], [best[2]], conf

def write(qid, ans, cites, conf):
    os.makedirs(OUT_DIR, exist_ok=True)
    rec = {"answer": ans, "citations": cites, "sources": cites,
           "source_url": cites[0] if cites else "", "confidence": conf}
    p = os.path.join(OUT_DIR, f"{qid}_output.json")
    with open(p + ".tmp", "w") as f: json.dump(rec, f, ensure_ascii=False)
    os.replace(p + ".tmp", p)
    return rec

def load_jobs(a):
    if a.query:
        return [(a.id or "q1", a.query, a.url)]
    if os.environ.get("QUERY"):
        return [(os.environ.get("QUERY_ID", "q1"), os.environ["QUERY"], os.environ.get("START_URL"))]
    jobs = []
    for f in sorted(glob.glob(os.path.join(a.input, "*.json"))):
        d = json.load(open(f))
        for it in (d if isinstance(d, list) else [d]):
            jobs.append((str(it.get("id") or it.get("query_id") or os.path.basename(f)[:-5]),
                         it.get("query") or it.get("question"), it.get("url") or it.get("start_url")))
    return jobs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query"); ap.add_argument("--url"); ap.add_argument("--id")
    ap.add_argument("--input", default=os.environ.get("INPUT_DIR", "/app/input"))
    a = ap.parse_args()
    for qid, q, u in load_jobs(a):
        write(qid, "", [], 0.0)  # placeholder first
        try:
            ans, cites, conf = run(qid, q, u)
        except Exception as e:
            print("error:", e, file=sys.stderr); continue
        print(json.dumps(write(qid, ans, cites, conf), ensure_ascii=False))

if __name__ == "__main__":
    main()
