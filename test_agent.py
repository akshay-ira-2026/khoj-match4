import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")
FIXTURES = {
 "contact.html": "<html><body><p>Support phone: +91 80 4567 8910</p><p>Email: help@acme.example</p></body></html>\n",
 "home.html": "<html><head><title>Acme Cloud</title><script>var x=1;</script></head><body>\n<nav><a href=\"pricing.html\">Pricing plans</a> <a href=\"releases.html\">Release notes</a> <a href=\"contact.html\">Contact us</a></nav>\n<p>Acme Cloud was founded in March 2014 by Priya Raman in Pune.</p></body></html>\n",
 "pricing.html": "<html><body><h1>Pricing</h1><table><tr><th>Plan</th><th>Price</th></tr>\n<tr><td>Starter</td><td>$9 per month</td></tr><tr><td>Pro plan</td><td>$29 per month</td></tr></table></body></html>\n",
 "releases.html": "<html><body><h2>Release notes</h2><p>Latest version 4.2.1 released on 12 Oct 2026.</p><p>Previous version 4.1.0.</p></body></html>\n"
}
SITE = tempfile.mkdtemp()
for _n, _h in FIXTURES.items():
    open(os.path.join(SITE, _n), "w").write(_h)
FX = os.path.join(SITE, "home.html")
CASES = [
    ("price", "What is the price of the Pro plan?", "$29 per month"),
    ("version", "What is the latest version?", "4.2.1"),
    ("phone", "What is the support phone number?", "+91 80 4567 8910"),
    ("email", "What is the support e-mail address?", "help@acme.example"),
    ("founded", "When was Acme Cloud founded?", "March 2014"),
    ("founder", "Who is the founder of Acme Cloud?", "Priya Raman"),
]
def test_all():
    out = tempfile.mkdtemp(); ok = 0
    for qid, q, want in CASES:
        env = dict(os.environ, OUTPUT_DIR=out, KHOJ_LLM="0")
        subprocess.run([sys.executable, APP, "--id", qid, "--query", q, "--url", FX], env=env, check=True, capture_output=True)
        rec = json.load(open(os.path.join(out, f"{qid}_output.json")))
        assert set(rec) == {"answer", "citations", "sources", "source_url", "confidence"}
        good = want.lower() in rec["answer"].lower()
        ok += good
        print(("PASS" if good else "FAIL"), qid, "->", rec["answer"], "|", rec["source_url"].split("/")[-1], rec["confidence"])
    print(f"{ok}/{len(CASES)}")
    assert ok >= 5
if __name__ == "__main__":
    test_all()
