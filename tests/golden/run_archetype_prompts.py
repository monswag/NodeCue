"""Golden-test harness for archetype prompts.

Two checks (both static — no LLM/Blender needed):

1. COVERAGE — every archetype in archetypes.yaml has ≥ MIN_PER_ARCHETYPE
   prompts tagged against it.

2. REFERENCE_CONSISTENCY — for each prompt with a `reference` key, the
   archetype_detector's classification of that reference group must match the
   prompt's `expected.primary`. This is the anchor that keeps the curated
   prompt set honest against the detector's current rules.

Later phases will extend this harness to run the Tier-2 planner (LLM →
plan → builder) for each prompt and classify the generated tree.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import yaml

from archetype_detector import _collect_nodes, detect_group

ROOT = Path(__file__).resolve().parents[2]
DETECT_SPEC = ROOT / "tests" / "golden" / "archetypes.yaml"
PROMPTS = ROOT / "tests" / "golden" / "archetype_prompts.yaml"
REFS_DIR = ROOT / "references"

MIN_PER_ARCHETYPE = 3


def _load_spec() -> dict:
    return yaml.safe_load(DETECT_SPEC.read_text(encoding="utf-8"))


def _load_prompts() -> list[dict]:
    data = yaml.safe_load(PROMPTS.read_text(encoding="utf-8")) or {}
    return data.get("prompts") or []


def _load_reference_blob(ref_key: str) -> tuple[dict, dict] | None:
    """Locate a reference group's JSON by its "{blend}/{group}" key.

    Returns (payload, per-blend group map) or None if not found. The group
    map is needed so detect_group can do cross-layer signature union.
    """
    try:
        blend, group = ref_key.split("/", 1)
    except ValueError:
        return None

    blend_dir = REFS_DIR / blend
    if not blend_dir.exists():
        return None

    per_blend: dict[str, dict] = {}
    target_payload: dict | None = None
    for json_file in sorted(blend_dir.glob("*.json")):
        if json_file.name.endswith("-summary.json"):
            continue
        try:
            payload = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        data = payload.get("data") or {}
        g = data.get("group", "")
        per_blend[g] = data
        if g == group:
            target_payload = payload

    if target_payload is None:
        return None
    return target_payload, per_blend


def check_coverage(prompts: list[dict], spec: dict) -> tuple[bool, list[str]]:
    archetype_ids = list((spec.get("archetypes") or {}).keys())
    counts: Counter = Counter()
    for p in prompts:
        pid = (p.get("expected") or {}).get("primary")
        if pid:
            counts[pid] += 1

    gaps: list[str] = []
    for aid in archetype_ids:
        if counts[aid] < MIN_PER_ARCHETYPE:
            gaps.append(f"{aid}: {counts[aid]}/{MIN_PER_ARCHETYPE}")
    return (not gaps, gaps)


def check_reference_consistency(
    prompts: list[dict], spec: dict
) -> list[dict]:
    rows: list[dict] = []
    for p in prompts:
        ref = p.get("reference")
        if not ref:
            continue
        loaded = _load_reference_blob(ref)
        if loaded is None:
            rows.append(
                {
                    "id": p["id"],
                    "reference": ref,
                    "status": "NOT_FOUND",
                    "expected": (p.get("expected") or {}).get("primary"),
                    "detected": None,
                }
            )
            continue
        payload, per_blend = loaded
        result = detect_group(
            payload["data"],
            spec,
            blend=payload.get("blend_name", ""),
            groups_by_name=per_blend,
        )
        expected = (p.get("expected") or {}).get("primary")
        if result.primary == expected:
            status = "MATCH"
        elif expected in ([result.primary] + result.secondaries):
            status = "SECONDARY"
        else:
            status = "MISMATCH"

        # Sanity-check: does the reference actually contain the bl_idnames
        # the prompt expects a generated plan to emit? If the reference is
        # missing these, either the prompt picked the wrong reference or
        # the required list is too tight.
        required = (p.get("expected") or {}).get("required_bl_idnames") or []
        present = {n.get("bl_idname", "") for n in _collect_nodes(payload["data"])}
        missing = [bl for bl in required if bl not in present]

        rows.append(
            {
                "id": p["id"],
                "reference": ref,
                "status": status,
                "expected": expected,
                "detected": result.primary,
                "secondaries": result.secondaries,
                "missing_bl_idnames": missing,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human summary.",
    )
    args = parser.parse_args()

    spec = _load_spec()
    prompts = _load_prompts()

    cov_ok, gaps = check_coverage(prompts, spec)
    ref_rows = check_reference_consistency(prompts, spec)

    ref_counts = Counter(r["status"] for r in ref_rows)

    summary = {
        "total_prompts": len(prompts),
        "coverage_ok": cov_ok,
        "coverage_gaps": gaps,
        "reference_checks": len(ref_rows),
        "reference_results": dict(ref_counts),
        "overall_pass": cov_ok and ref_counts.get("MISMATCH", 0) == 0,
    }

    if args.json:
        print(
            json.dumps(
                {"summary": summary, "rows": ref_rows},
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    print("=== Archetype prompts golden test ===")
    print(f"Total prompts: {summary['total_prompts']}")
    print()
    print(f"Coverage (≥ {MIN_PER_ARCHETYPE}/archetype): "
          f"{'PASS' if cov_ok else 'FAIL'}")
    for gap in gaps:
        print(f"  - gap: {gap}")
    print()
    print(f"Reference consistency ({summary['reference_checks']} checked):")
    for status, count in sorted(ref_counts.items()):
        print(f"  {status}: {count}")
    mismatches = [r for r in ref_rows if r["status"] in ("MISMATCH", "NOT_FOUND")]
    secondaries = [r for r in ref_rows if r["status"] == "SECONDARY"]
    bl_gaps = [r for r in ref_rows if r.get("missing_bl_idnames")]
    if mismatches:
        print()
        print("  !! Mismatches:")
        for r in mismatches:
            print(
                f"    {r['id']} → ref={r['reference']} "
                f"expected={r['expected']} detected={r['detected']}"
            )
    if secondaries:
        print()
        print("  ~~ Secondary-only hits (review):")
        for r in secondaries:
            print(
                f"    {r['id']} → ref={r['reference']} "
                f"expected={r['expected']} detected={r['detected']} "
                f"secondaries={r['secondaries']}"
            )
    if bl_gaps:
        print()
        print("  ?? Required bl_idnames missing from chosen reference:")
        for r in bl_gaps:
            print(f"    {r['id']}: missing {r['missing_bl_idnames']}")

    print()
    summary["bl_idname_gaps"] = len(bl_gaps)
    summary["overall_pass"] = (
        summary["overall_pass"]
        and ref_counts.get("NOT_FOUND", 0) == 0
        and len(bl_gaps) == 0
    )
    print("OVERALL:", "PASS" if summary["overall_pass"] else "FAIL")


if __name__ == "__main__":
    main()
