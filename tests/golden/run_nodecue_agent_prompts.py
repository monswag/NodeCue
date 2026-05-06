"""Run NodeCue's real-model planning eval against archetype prompts.

This harness sends only the user-facing prompt to the NodeCue agent planner.
Expected labels and required node ids are used locally for scoring after the
model returns a strict JSON AgentPlan.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nodecue_agent import ProviderConfig, plan_geometry_prompt  # noqa: E402

PROMPTS_PATH = ROOT / "tests" / "golden" / "archetype_prompts.yaml"
ARCHETYPES_PATH = ROOT / "tests" / "golden" / "archetypes.yaml"
DEFAULT_SKILL_PATH = ROOT / "nodecue" / "skills" / "geometry-nodes"


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_prompts(prompt_id: str | None, limit: int | None) -> list[dict[str, Any]]:
    prompts = _load_yaml(PROMPTS_PATH).get("prompts") or []
    if prompt_id:
        prompts = [entry for entry in prompts if entry.get("id") == prompt_id]
        if not prompts:
            raise SystemExit(f"prompt id not found: {prompt_id}")
    if limit is not None:
        prompts = prompts[:limit]
    return prompts


def _archetype_context() -> str:
    data = _load_yaml(ARCHETYPES_PATH)
    lines: list[str] = []
    for archetype_id, spec in (data.get("archetypes") or {}).items():
        name = spec.get("name", "")
        role = spec.get("role_hint", "")
        lines.append(f"- {archetype_id}: {name}. Role: {role}")
    return "\n".join(lines)


def _score(entry: dict[str, Any], plan: dict[str, Any] | None, error: str | None) -> dict[str, Any]:
    expected = entry.get("expected") or {}
    expected_primary = expected.get("primary", "")
    required = expected.get("required_bl_idnames") or []
    if error or plan is None:
        return {
            "id": entry.get("id"),
            "status": "ERROR",
            "expected_primary": expected_primary,
            "actual_primary": None,
            "primary_match": False,
            "required_bl_idnames": required,
            "missing_bl_idnames": required,
            "node_coverage": 0.0,
            "error": error,
            "plan": plan,
        }

    actual_primary = plan.get("primary_archetype")
    bl_idnames = set(plan.get("bl_idnames") or [])
    missing = [node_id for node_id in required if node_id not in bl_idnames]
    coverage = 1.0 if not required else (len(required) - len(missing)) / len(required)
    primary_match = actual_primary == expected_primary
    return {
        "id": entry.get("id"),
        "status": "PASS" if primary_match and not missing else "FAIL",
        "expected_primary": expected_primary,
        "actual_primary": actual_primary,
        "primary_match": primary_match,
        "required_bl_idnames": required,
        "missing_bl_idnames": missing,
        "node_coverage": coverage,
        "error": None,
        "plan": plan,
    }


def _summary(rows: list[dict[str, Any]], min_primary_rate: float, min_node_coverage: float) -> dict[str, Any]:
    total = len(rows)
    errors = sum(1 for row in rows if row["status"] == "ERROR")
    passes = sum(1 for row in rows if row["status"] == "PASS")
    primary_matches = sum(1 for row in rows if row["primary_match"])
    primary_rate = primary_matches / total if total else 0.0

    required_total = sum(len(row["required_bl_idnames"]) for row in rows)
    missing_total = sum(len(row["missing_bl_idnames"]) for row in rows)
    node_coverage = (
        (required_total - missing_total) / required_total if required_total else 1.0
    )
    threshold_pass = primary_rate >= min_primary_rate and node_coverage >= min_node_coverage
    return {
        "total": total,
        "passes": passes,
        "failures": sum(1 for row in rows if row["status"] == "FAIL"),
        "errors": errors,
        "primary_accuracy": primary_rate,
        "required_node_coverage": node_coverage,
        "min_primary_rate": min_primary_rate,
        "min_node_coverage": min_node_coverage,
        "overall_pass": errors == 0 and threshold_pass,
    }


def _provider_from_args(args: argparse.Namespace) -> ProviderConfig:
    if args.provider in {"openrouter", "openai-compatible", "anthropic-compatible"}:
        return ProviderConfig(
            kind=args.provider,
            model=args.model or os.environ.get("NODECUE_AGENT_MODEL", ""),
            base_url=args.base_url or os.environ.get("NODECUE_AGENT_BASE_URL", ""),
            api_key_env=args.api_key_env or os.environ.get("NODECUE_AGENT_API_KEY_ENV", ""),
        )
    return ProviderConfig(kind="mock")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--prompt-id", help="Run one prompt id")
    parser.add_argument("--limit", type=int, help="Run only the first N prompts")
    parser.add_argument(
        "--skill-path",
        type=Path,
        default=DEFAULT_SKILL_PATH,
        help="Path to the Geometry Nodes skill directory",
    )
    parser.add_argument(
        "--provider",
        choices=("mock", "openrouter", "openai-compatible", "anthropic-compatible"),
        default=os.environ.get("NODECUE_AGENT_PROVIDER", "mock"),
    )
    parser.add_argument("--model", default=os.environ.get("NODECUE_AGENT_MODEL", ""))
    parser.add_argument("--base-url", default=os.environ.get("NODECUE_AGENT_BASE_URL", ""))
    parser.add_argument(
        "--api-key-env",
        default=os.environ.get("NODECUE_AGENT_API_KEY_ENV", ""),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=int(os.environ.get("NODECUE_AGENT_TIMEOUT_SECONDS", "120")),
    )
    parser.add_argument(
        "--min-primary-rate",
        type=float,
        default=float(os.environ.get("NODECUE_AGENT_MIN_PRIMARY_RATE", "0")),
    )
    parser.add_argument(
        "--min-node-coverage",
        type=float,
        default=float(os.environ.get("NODECUE_AGENT_MIN_NODE_COVERAGE", "0")),
    )
    args = parser.parse_args()

    prompts = _load_prompts(args.prompt_id, args.limit)
    provider = _provider_from_args(args)
    context = _archetype_context()
    rows: list[dict[str, Any]] = []

    for entry in prompts:
        plan_payload: dict[str, Any] | None = None
        error: str | None = None
        try:
            plan = plan_geometry_prompt(
                entry["prompt"],
                args.skill_path,
                provider=provider,
                archetype_context=context,
                timeout_seconds=args.timeout_seconds,
            )
            plan_payload = plan.as_dict()
        except Exception as exc:
            error = str(exc)
        rows.append(_score(entry, plan_payload, error))

    summary = _summary(rows, args.min_primary_rate, args.min_node_coverage)
    payload = {"summary": summary, "rows": rows}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("=== NodeCue agent prompt eval ===")
        print(f"Provider: {provider.kind}")
        print(f"Model: {provider.model or '(none)'}")
        print(f"Prompts: {summary['total']}")
        print(f"Pass / Fail / Error: {summary['passes']} / {summary['failures']} / {summary['errors']}")
        print(f"Primary accuracy: {summary['primary_accuracy']:.2%}")
        print(f"Required node coverage: {summary['required_node_coverage']:.2%}")
        for row in rows:
            if row["status"] != "PASS":
                print(
                    f"- {row['status']} {row['id']}: expected={row['expected_primary']} "
                    f"actual={row['actual_primary']} missing={row['missing_bl_idnames']} "
                    f"error={row['error']}"
                )

    return 0 if summary["overall_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
