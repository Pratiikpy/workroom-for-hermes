import json, os, random, sys, urllib.request
d = json.load(open(sys.argv[1]))["sample"]
acc = [s for s in d if s["decision"] == "accept"]
random.Random(77).shuffle(acc)
items = acc[:60]
lines = []
for i, s in enumerate(items):
    heads = " / ".join(s["heads"][-3:]) if s["heads"] else s["text"][:160]
    lines.append(f'{i}. company={s["company"]} number="{s["number"]}" document_context="{heads[:200]}" linked_to_source_row="{s["workroom"][0][0]}" period="{s["workroom"][1][0]}"')
prompt = ("You are an independent auditor. Each item is a number in a company's earnings press release that software linked to a row and period in the company's XBRL financial data workbook. "
          "Judge whether the link is semantically right: does the press-release context describe the same financial item as the linked row (net sales = revenue, net income = net income attributable, etc.), ignoring whether the period is exactly right. "
          "Answer ONLY a JSON array of objects {\"i\": index, \"verdict\": \"correct\"|\"wrong\"|\"unclear\"}.\n\n" + "\n".join(lines))
body = json.dumps({"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}).encode()
req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent", data=body, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"], "Content-Type": "application/json"})
out = json.load(urllib.request.urlopen(req, timeout=120))
verdicts = json.loads(out["candidates"][0]["content"]["parts"][0]["text"])
from collections import Counter
print(Counter(v["verdict"] for v in verdicts), len(items))
for v in verdicts:
    if v["verdict"] != "correct":
        s = items[v["i"]]; print(v["verdict"], s["company"], s["number"], "|", " / ".join(s["heads"][-2:])[:70] or s["text"][:70], "=>", s["workroom"][0][0][:40])
