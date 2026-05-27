import json
from collections import Counter, defaultdict

path = r"C:\Users\uaa\Desktop\мусор\проект2 (чатбот)\back\chatbot\tests\rag_benchmark_results.json"
d = json.load(open(path, encoding="utf-8"))


def cat(sf: str) -> str:
    if "СТО" in sf or sf.startswith("2939") or sf.startswith("8."):
        return "gost"
    if sf.startswith("ОТ ") or sf.startswith("2024-"):
        return "ot"
    return "re"


cats = defaultdict(lambda: {"n": 0, "good": 0, "partial": 0, "fail": 0, "ret": 0, "ms": 0})
for r in d["results"]:
    c = cat(r["source_file"])
    v = cats[c]
    v["n"] += 1
    q = r["quality"]
    if q not in ("good", "partial", "fail"):
        q = "partial" if not r["is_fallback"] else "fail"
    v[q] += 1
    v["ret"] += int(r["retrieval_hit"])
    v["ms"] += r["total_ms"]

out = {
    "summary": {
        k: d[k]
        for k in (
            "total_questions",
            "total_files",
            "overall_score_pct",
            "overall_retrieval_pct",
            "overall_good",
            "overall_partial",
            "overall_fail",
            "avg_total_ms",
            "generated_at",
        )
    },
    "categories": {},
    "per_file": d["per_file"],
    "worst_files": sorted(d["per_file"], key=lambda x: x["score_pct"])[:5],
    "best_files": sorted(d["per_file"], key=lambda x: -x["score_pct"])[:5],
    "fail_by_file": Counter(r["source_file"] for r in d["results"] if r["quality"] == "fail").most_common(),
}

for c, v in cats.items():
    n = v["n"]
    out["categories"][c] = {
        "questions": n,
        "score_pct": round(100 * (v["good"] + 0.5 * v["partial"]) / n, 1),
        "retrieval_pct": round(100 * v["ret"] / n, 1),
        "good": v["good"],
        "partial": v["partial"],
        "fail": v["fail"],
        "avg_ms": round(v["ms"] / n, 1),
    }

dest = path.replace("results", "canvas_data")
json.dump(out, open(dest, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(json.dumps(out, ensure_ascii=False, indent=2))
