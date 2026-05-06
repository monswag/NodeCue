"""Local NodeCue agent sidecar prototype.

This module is intentionally Blender-free so it can run in a separate Python
process later. The current implementation proves the first integration slice:
load the Geometry Nodes skill, call a mocked Blender tool, and stream events
that the addon UI can display.
"""

from __future__ import annotations

import json
import os
import shlex
import socket
import struct
import subprocess
import tempfile
import textwrap
import urllib.error
import urllib.request
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Callable, Iterable, Literal, Mapping

from pydantic import BaseModel, Field

from nodecue.bpy_recipes import (
    ACTION_TO_COMMAND,
    json_safe,
    normalize_action,
    supported_action_types,
)


AgentMode = Literal["generate", "explain", "modify"]
ProviderKind = Literal[
    "openai",
    "anthropic",
    "anthropic-compatible",
    "openai-compatible",
    "openrouter",
    "mock",
]
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"
ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_LOCAL_OPENAI_BASE_URL = "http://127.0.0.1:11434/v1"
ANTHROPIC_VERSION = "2023-06-01"


class StageNodeSpec(BaseModel):
    bl_idname: str = Field(description="Exact Blender node bl_idname, for example GeometryNodeSetPosition.")
    name: str = Field(default="", description="Temporary alias for later links in this stage. It is not written to Blender node.name.")
    label: str = Field(default="", description="Ignored for ordinary nodes. Put explanations on frames, not node labels.")
    location_x: float = Field(default=0.0, description="Node editor x location.")
    location_y: float = Field(default=0.0, description="Node editor y location.")


class StageLinkSpec(BaseModel):
    from_node: str = Field(description="Source node name from this stage or readback.")
    from_socket: str = Field(description="Source socket name or identifier.")
    to_node: str = Field(description="Destination node name from this stage or readback.")
    to_socket: str = Field(description="Destination socket name or identifier.")


class StageSocketDefaultSpec(BaseModel):
    node_name: str = Field(description="Node name from this stage or readback.")
    socket_name: str = Field(description="Input socket name or identifier whose default value should be set.")
    value_json: str = Field(default="", description="JSON value for the socket default, e.g. 2.0, true, or [0,0,1].")


class StageNodePropertySpec(BaseModel):
    node_name: str = Field(description="Node name from this stage or readback.")
    property_name: str = Field(
        description="Node RNA property only, e.g. operation, data_type, or domain. Never use inputs[], outputs[], or default_value here.",
    )
    value_json: str = Field(default="", description="JSON value for the node RNA property.")


class StageGroupSocketSpec(BaseModel):
    name: str = Field(description="Group interface socket label.")
    socket_type: str = Field(default="NodeSocketFloat", description="Blender socket type, e.g. NodeSocketFloat.")
    in_out: str = Field(default="INPUT", description="INPUT or OUTPUT.")
    default_value_json: str = Field(default="", description="Optional JSON default value.")


class StageFrameSpec(BaseModel):
    node_names: list[str] = Field(description="Node names to parent to this teaching frame.")
    label: str = Field(default="", description="Visible frame label.")
    frame_name: str = Field(default="", description="Optional stable frame name for upsert/update.")


def stage_node_property_misuse_error(
    specs: Iterable[StageNodePropertySpec],
) -> dict[str, Any] | None:
    """Return a tool error when socket defaults are sent as node properties."""

    invalid: list[dict[str, str]] = []
    for spec in specs:
        property_name = str(spec.property_name or "")
        lowered = property_name.lower()
        if "inputs[" in lowered or "outputs[" in lowered or "default_value" in lowered:
            invalid.append(
                {
                    "node_name": spec.node_name,
                    "property_name": property_name,
                }
            )
    if not invalid:
        return None
    return {
        "error": "Socket defaults must use socket_defaults, not node_properties. node_properties is only for node RNA properties such as operation, data_type, or domain.",
        "invalid_node_properties": invalid,
        "repair_hint": "Move each socket default write into socket_defaults with node_name, socket_name, and value_json.",
    }


def should_skip_stage_arrange(action_count: int) -> bool:
    """Avoid expensive auto-layout on large generated stages."""

    return action_count > 18


def coerce_stage_socket_value(value: Any, *, socket_type: str = "") -> Any:
    """Coerce quoted numeric socket defaults while preserving string sockets."""

    if isinstance(value, str) and "string" not in str(socket_type).lower():
        stripped = value.strip()
        if stripped and stripped.lower() not in {"nan", "inf", "+inf", "-inf", "infinity"}:
            try:
                return float(stripped) if any(marker in stripped for marker in (".", "e", "E")) else int(stripped)
            except ValueError:
                return value
    return value


@dataclass(frozen=True)
class ProviderConfig:
    kind: ProviderKind = "mock"
    model: str = ""
    base_url: str = ""
    api_key_env: str = ""
    timeout_seconds: int = 120
    temperature: float = 0.0

    @property
    def uses_real_model(self) -> bool:
        return self.kind != "mock"

    @property
    def normalized_kind(self) -> ProviderKind:
        if self.kind == "openrouter":
            return "openai-compatible"
        return self.kind

    @property
    def requires_api_key(self) -> bool:
        return self.kind in {"openai", "anthropic", "openrouter"}

    def resolved_base_url(self) -> str:
        if self.kind == "openrouter":
            return (self.base_url or OPENROUTER_BASE_URL).rstrip("/")
        if self.kind == "openai":
            return (self.base_url or OPENAI_BASE_URL).rstrip("/")
        if self.kind == "anthropic":
            return (self.base_url or ANTHROPIC_BASE_URL).rstrip("/")
        if self.kind == "anthropic-compatible":
            return (self.base_url or ANTHROPIC_BASE_URL).rstrip("/")
        if self.kind == "openai-compatible":
            return (self.base_url or DEFAULT_LOCAL_OPENAI_BASE_URL).rstrip("/")
        return self.base_url.rstrip("/")

    def resolved_api_key_env(self) -> str:
        if self.api_key_env:
            return self.api_key_env
        if self.kind == "openrouter":
            return "OPENROUTER_API_KEY"
        if self.kind == "openai":
            return "OPENAI_API_KEY"
        if self.kind in {"anthropic", "anthropic-compatible"}:
            return "ANTHROPIC_API_KEY"
        return ""

    @classmethod
    def from_env(cls) -> "ProviderConfig":
        raw_kind = os.environ.get("NODECUE_AGENT_PROVIDER", "mock").strip() or "mock"
        kind: ProviderKind = raw_kind if raw_kind in {
            "mock",
            "openai",
            "anthropic",
            "anthropic-compatible",
            "openai-compatible",
            "openrouter",
        } else "mock"
        try:
            timeout_seconds = int(os.environ.get("NODECUE_AGENT_TIMEOUT_SECONDS", "120"))
        except ValueError:
            timeout_seconds = 120
        try:
            temperature = float(os.environ.get("NODECUE_AGENT_TEMPERATURE", "0"))
        except ValueError:
            temperature = 0.0
        return cls(
            kind=kind,
            model=os.environ.get("NODECUE_AGENT_MODEL", "").strip(),
            base_url=os.environ.get("NODECUE_AGENT_BASE_URL", "").strip(),
            api_key_env=os.environ.get("NODECUE_AGENT_API_KEY_ENV", "").strip(),
            timeout_seconds=timeout_seconds,
            temperature=temperature,
        )


@dataclass(frozen=True)
class SkillBundle:
    name: str
    root: Path
    system_prompt: str
    skill_text: str

    @classmethod
    def load(cls, root: str | Path) -> "SkillBundle":
        skill_root = Path(root).expanduser().resolve()
        skill_path = skill_root / "SKILL.md"
        if not skill_path.exists():
            raise FileNotFoundError(f"missing SKILL.md at {skill_path}")

        system_prompt_path = skill_root / "SYSTEM_PROMPT.md"
        system_prompt = (
            system_prompt_path.read_text(encoding="utf-8")
            if system_prompt_path.exists()
            else ""
        )
        return cls(
            name=skill_root.name,
            root=skill_root,
            system_prompt=system_prompt,
            skill_text=skill_path.read_text(encoding="utf-8"),
        )

    def instruction_excerpt(self, limit: int = 1400) -> str:
        parts = [self.system_prompt.strip(), self.skill_text.strip()]
        text = "\n\n".join(p for p in parts if p)
        return text[:limit]

    def _safe_path(self, path: str | Path) -> Path:
        raw = str(path).strip()
        if not raw:
            raise ValueError("skill path is empty")
        if Path(raw).is_absolute() or ".." in Path(raw).parts:
            raise ValueError("skill path must be relative to the skill root")
        resolved = (self.root / raw).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ValueError("skill path escapes the skill root")
        if not resolved.is_file():
            raise FileNotFoundError(f"skill file not found: {raw}")
        return resolved

    def list_files(self) -> dict[str, Any]:
        files: list[str] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            if path.suffix.lower() not in {".md", ".yaml", ".yml", ".json", ".txt"}:
                continue
            files.append(path.relative_to(self.root).as_posix())
        return {"root": str(self.root), "files": files}

    def read_file(
        self,
        path: str | Path,
        *,
        start_line: int = 1,
        max_lines: int = 160,
    ) -> dict[str, Any]:
        file_path = self._safe_path(path)
        lines = file_path.read_text(encoding="utf-8").splitlines()
        safe_start = max(1, int(start_line or 1))
        safe_max = max(1, min(int(max_lines or 160), 240))
        selected = lines[safe_start - 1 : safe_start - 1 + safe_max]
        return {
            "path": file_path.relative_to(self.root).as_posix(),
            "start_line": safe_start,
            "end_line": safe_start + len(selected) - 1 if selected else safe_start - 1,
            "total_lines": len(lines),
            "content": "\n".join(selected),
        }

    def search(
        self,
        query: str,
        *,
        max_results: int = 8,
        context_lines: int = 2,
    ) -> dict[str, Any]:
        needle = str(query or "").strip().lower()
        if not needle:
            return {"query": query, "matches": []}
        safe_max = max(1, min(int(max_results or 8), 20))
        safe_context = max(0, min(int(context_lines or 2), 5))
        matches: list[dict[str, Any]] = []
        for relative in self.list_files()["files"]:
            path = self._safe_path(relative)
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for index, line in enumerate(lines):
                if needle not in line.lower():
                    continue
                start = max(0, index - safe_context)
                end = min(len(lines), index + safe_context + 1)
                matches.append(
                    {
                        "path": relative,
                        "line": index + 1,
                        "context": "\n".join(lines[start:end]),
                    }
                )
                if len(matches) >= safe_max:
                    return {"query": query, "matches": matches}
        return {"query": query, "matches": matches}


@dataclass(frozen=True)
class AgentRequest:
    prompt: str
    mode: AgentMode
    skill_path: str
    provider: ProviderConfig = ProviderConfig()
    image_path: str = ""


@dataclass(frozen=True)
class StreamEvent:
    type: Literal["status", "tool_call", "tool_result", "final", "error"]
    message: str
    data: dict[str, Any] | None = None


@dataclass(frozen=True)
class AgentPlan:
    primary_archetype: str
    bl_idnames: list[str]
    rationale: str
    confidence: float

    @classmethod
    def from_json_text(cls, text: str) -> "AgentPlan":
        try:
            payload = json.loads(text.strip())
        except json.JSONDecodeError as exc:
            raise ValueError(f"agent response was not strict JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("agent response JSON must be an object")

        primary = payload.get("primary_archetype")
        bl_idnames = payload.get("bl_idnames")
        rationale = payload.get("rationale")
        confidence = payload.get("confidence")
        if not isinstance(primary, str) or not primary.strip():
            raise ValueError("AgentPlan.primary_archetype must be a non-empty string")
        if not isinstance(bl_idnames, list) or not all(isinstance(x, str) for x in bl_idnames):
            raise ValueError("AgentPlan.bl_idnames must be a list of strings")
        if not isinstance(rationale, str):
            raise ValueError("AgentPlan.rationale must be a string")
        if not isinstance(confidence, int | float):
            raise ValueError("AgentPlan.confidence must be a number")

        unique_bl_idnames = list(dict.fromkeys(x.strip() for x in bl_idnames if x.strip()))
        return cls(
            primary_archetype=primary.strip(),
            bl_idnames=unique_bl_idnames,
            rationale=rationale.strip(),
            confidence=max(0.0, min(1.0, float(confidence))),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "primary_archetype": self.primary_archetype,
            "bl_idnames": self.bl_idnames,
            "rationale": self.rationale,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class NodeCueAction:
    """One internal, node-scoped tool request.

    This is an execution boundary for NodeCue's built-in agent, not reusable GN
    knowledge. The skill explains what to build; this schema constrains what
    the model may ask NodeCue to execute.
    """

    type: str
    intent: str
    parameters: dict[str, Any]
    expected_readback: dict[str, Any]
    failure_recovery: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "NodeCueAction":
        normalized = normalize_action(payload)
        return cls(
            type=normalized["type"],
            intent=normalized["intent"],
            parameters=normalized["parameters"],
            expected_readback=dict(normalized.get("expected_readback") or {}),
            failure_recovery=normalized["failure_recovery"],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "intent": self.intent,
            "parameters": self.parameters,
            "expected_readback": self.expected_readback,
            "failure_recovery": self.failure_recovery,
        }


@dataclass(frozen=True)
class ActionSlice:
    intent: str
    actions: list[NodeCueAction]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ActionSlice":
        intent = str(payload.get("intent") or "").strip()
        raw_actions = payload.get("actions")
        if not isinstance(raw_actions, list) or not raw_actions:
            raise ValueError("ActionSlice.actions must be a non-empty list")
        return cls(
            intent=intent,
            actions=[NodeCueAction.from_mapping(action) for action in raw_actions],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "actions": [action.as_dict() for action in self.actions],
        }


@dataclass(frozen=True)
class NodeCueActionPlan:
    """Internal tool-call plan for NodeCue's built-in agent.

    It replaces the old custom-MCP tool surface inside NodeCue: the model emits
    small, validated node actions, the executor maps them to bpy recipes, and
    readback/verifier feedback drives repair slices. GN domain knowledge stays
    in skills/rules/patterns.
    """

    mode: AgentMode
    slices: list[ActionSlice]
    final_explanation_goal: str

    @classmethod
    def from_json_text(cls, text: str) -> "NodeCueActionPlan":
        try:
            payload = json.loads(text.strip())
        except json.JSONDecodeError as exc:
            raise ValueError(f"action plan response was not strict JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("action plan JSON must be an object")

        mode = str(payload.get("mode") or "generate").strip()
        if mode not in {"generate", "explain", "modify"}:
            raise ValueError("action plan mode must be generate, explain, or modify")
        raw_slices = payload.get("slices")
        if not isinstance(raw_slices, list) or not raw_slices:
            raise ValueError("action plan must contain at least one slice")

        return cls(
            mode=mode,  # type: ignore[arg-type]
            slices=[ActionSlice.from_mapping(slice_payload) for slice_payload in raw_slices],
            final_explanation_goal=str(payload.get("final_explanation_goal") or "").strip(),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "slices": [slice_.as_dict() for slice_ in self.slices],
            "final_explanation_goal": self.final_explanation_goal,
        }


class MockBlenderBridge:
    """Blender bridge stand-in for the sidecar prototype."""

    def read_active_node_tree(self) -> dict[str, Any]:
        return {
            "ok": True,
            "tree_name": "Mock Active Geometry Nodes",
            "nodes": [],
            "links": [],
        }

    def create_node_tree(self, name: str) -> dict[str, Any]:
        return {"ok": True, "tree_name": name, "created": True}

    def execute_action(self, action: NodeCueAction) -> dict[str, Any]:
        if action.type == "read_active_node_tree":
            return self.read_active_node_tree()
        if action.type == "create_node_tree":
            return self.create_node_tree(str(action.parameters.get("name") or "NodeCue"))
        return {
            "ok": True,
            "mocked": True,
            "action_type": action.type,
            "parameters": action.parameters,
        }


class NodeCueAgentRunner:
    """Small sidecar runner shaped like the future Agents SDK integration."""

    def __init__(self, bridge: MockBlenderBridge | None = None):
        self.bridge = bridge or MockBlenderBridge()

    def stream(self, request: AgentRequest) -> Iterable[StreamEvent]:
        prompt = request.prompt.strip()
        if not prompt:
            yield StreamEvent("error", "Prompt is empty")
            return

        try:
            skill = SkillBundle.load(request.skill_path)
        except Exception as exc:
            yield StreamEvent("error", str(exc))
            return

        yield StreamEvent(
            "status",
            f"Loaded skill '{skill.name}' from {skill.root}",
            {"skill_excerpt": skill.instruction_excerpt()},
        )

        try:
            action_plan = plan_nodecue_actions(
                prompt,
                request.mode,
                request.skill_path,
                provider=request.provider,
            )
        except Exception as exc:
            yield StreamEvent("error", str(exc))
            return

        yield StreamEvent(
            "status",
            f"Planned {len(action_plan.slices)} node action slice(s)",
            action_plan.as_dict(),
        )
        results: list[dict[str, Any]] = []
        for slice_index, slice_ in enumerate(action_plan.slices, start=1):
            yield StreamEvent("status", f"Slice {slice_index}: {slice_.intent}")
            for action in slice_.actions:
                yield StreamEvent("tool_call", action.type, action.as_dict())
                result = self.bridge.execute_action(action)
                results.append({"action": action.as_dict(), "result": result})
                yield StreamEvent("tool_result", f"{action.type} completed", result)

        yield StreamEvent(
            "final",
            action_plan.final_explanation_goal
            or "NodeCue action planning path is wired with structured node actions.",
            {"mode": request.mode, "action_plan": action_plan.as_dict(), "results": results},
        )


def agents_sdk_available() -> bool:
    try:
        import agents  # noqa: F401
    except Exception:
        return False
    return True


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _agent_max_tokens(default: int = 4096) -> int:
    return _env_int("NODECUE_AGENT_MAX_TOKENS", default)


def _agent_reasoning_effort(default: str = "none") -> str:
    value = os.environ.get("NODECUE_AGENT_REASONING_EFFORT", default).strip().lower()
    return value if value in {"none", "minimal", "low", "medium", "high"} else default


def build_sdk_model(provider: ProviderConfig):
    """Build an OpenAI Agents SDK chat-completions model for NodeCue."""

    try:
        from agents import (
            AsyncOpenAI,
            ModelSettings,
            OpenAIChatCompletionsModel,
            set_tracing_disabled,
        )
    except Exception as exc:
        raise RuntimeError("Install openai-agents to run the SDK-backed agent") from exc

    if provider.kind not in {"openai", "openai-compatible", "openrouter"}:
        raise RuntimeError(f"Agents SDK runner does not support provider: {provider.kind}")
    if not provider.model:
        raise RuntimeError("missing NODECUE_AGENT_MODEL")

    api_key = _provider_api_key(provider) or "dummy"
    headers: dict[str, str] = {}
    if provider.kind == "openrouter":
        headers = {
            "HTTP-Referer": "https://github.com/NodeCue/NodeCue",
            "X-Title": "NodeCue Agent SDK Eval",
        }
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=provider.resolved_base_url(),
        default_headers=headers or None,
        timeout=provider.timeout_seconds,
    )

    if provider.kind != "openai" and not os.environ.get("OPENAI_API_KEY"):
        set_tracing_disabled(True)

    extra_body: dict[str, Any] = {}
    if provider.kind == "openrouter":
        effort = _agent_reasoning_effort()
        extra_body["reasoning"] = {"effort": effort, "exclude": True}

    settings = ModelSettings(
        temperature=provider.temperature,
        max_tokens=_agent_max_tokens(),
        parallel_tool_calls=False,
        include_usage=True,
        extra_body=extra_body or None,
    )
    model = OpenAIChatCompletionsModel(model=provider.model, openai_client=client)
    return model, settings


class HeadlessBlenderSession:
    """Execute NodeCue actions in a persistent .blend file via headless Blender."""

    def __init__(
        self,
        blend_path: str | Path,
        *,
        root: str | Path | None = None,
        timeout_seconds: int = 120,
        blender_command: str | None = None,
    ):
        self.blend_path = Path(blend_path).expanduser().resolve()
        self.root = Path(root or Path.cwd()).resolve()
        self.timeout_seconds = timeout_seconds
        self.blend_path.parent.mkdir(parents=True, exist_ok=True)
        command = blender_command or os.environ.get(
            "NODECUE_BLENDER_COMMAND", "conda run -n blender blender"
        )
        self.blender_command = shlex.split(command)
        self.current_tree_name = ""
        self.node_aliases: dict[str, str] = {}
        self.action_results: list[dict[str, Any]] = []
        self.stage_results: list[dict[str, Any]] = []
        self.skill_tool_calls: list[dict[str, Any]] = []
        self.skill_files_read: list[str] = []
        self.skill_search_queries: list[str] = []
        self.mode: AgentMode | str = ""

    def _map_node_name(self, name: Any) -> Any:
        if isinstance(name, str):
            return self.node_aliases.get(name, name)
        return name

    def _prepare_action(self, action_type: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
        prepared = normalize_action({"type": action_type, "parameters": parameters})
        params = dict(prepared["parameters"])
        if prepared["type"] not in {"create_node_tree", "read_active_node_tree", "list_asset_node_groups"}:
            if not params.get("tree_name"):
                params["tree_name"] = self.current_tree_name

        for key in ("from_node", "to_node", "node_name"):
            if key in params:
                params[key] = self._map_node_name(params[key])
        if isinstance(params.get("node_names"), list):
            params["node_names"] = [self._map_node_name(name) for name in params["node_names"]]

        prepared["parameters"] = params
        return prepared

    def execute(self, action_type: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
        action = self._prepare_action(action_type, parameters)
        result = self._run_blender_action(action)
        self._update_context(action, result)
        compact_result = self._compact_result(result)
        payload = {
            "tool_kind": "blender_tool",
            "action": action,
            "result": compact_result,
            "blend_path": str(self.blend_path),
        }
        self.action_results.append(payload)
        return json_safe(payload)

    def execute_stage(
        self,
        stage_goal: str,
        actions: list[Mapping[str, Any]],
        *,
        readback_after: bool = True,
        stop_on_error: bool = True,
    ) -> dict[str, Any]:
        raw_results: list[dict[str, Any]] = []
        failed_action: dict[str, Any] | None = None
        action_types = {
            str(action.get("type") or action.get("action") or "")
            for action in actions
            if isinstance(action, Mapping)
        }
        if self.mode == "generate" and not (action_types & {"create_node", "connect", "append_asset_node_group"}):
            stage = {
                "tool_kind": "blender_tool",
                "stage_goal": stage_goal,
                "ok": False,
                "raw_action_count": 0,
                "failed_action": {
                    "error": "Generate stages must include content node creation, asset insertion, or links; do not submit a create_node_tree-only stage.",
                    "action_types": sorted(action_types),
                },
                "results": [],
                "readback": None,
                "blend_path": str(self.blend_path),
            }
            self.stage_results.append(stage)
            return json_safe(stage)
        for raw_action in actions:
            try:
                action_type = str(raw_action.get("type") or raw_action.get("action") or "")
                raw_params = raw_action.get("parameters") or raw_action.get("params") or {}
                if not isinstance(raw_params, Mapping):
                    raise ValueError("action parameters must be an object")
                action = self._prepare_action(action_type, raw_params)
            except Exception as exc:
                failed_action = {"raw_action": json_safe(raw_action), "error": str(exc)}
                raw_results.append({"tool_kind": "blender_tool", "error": str(exc), "raw_action": json_safe(raw_action)})
                if stop_on_error:
                    break
                continue

            result = self._run_blender_action(action)
            compact_result = self._compact_result(result)
            self._update_context(action, result if isinstance(result, Mapping) else compact_result)
            payload = {
                "tool_kind": "blender_tool",
                "action": action,
                "result": compact_result,
                "blend_path": str(self.blend_path),
            }
            self.action_results.append(payload)
            raw_results.append(payload)
            if isinstance(compact_result, Mapping) and compact_result.get("error"):
                failed_action = payload
                if stop_on_error:
                    break

        readback = self.final_readback() if readback_after else None
        stage = {
            "tool_kind": "blender_tool",
            "stage_goal": stage_goal,
            "ok": failed_action is None,
            "raw_action_count": len(raw_results),
            "failed_action": failed_action,
            "results": raw_results,
            "readback": readback,
            "blend_path": str(self.blend_path),
        }
        self.stage_results.append(stage)
        return json_safe(stage)

    def read_active_node_tree(self) -> dict[str, Any]:
        return self.execute("read_active_node_tree", {})

    def final_readback(self) -> dict[str, Any]:
        action = self._prepare_action("read_active_node_tree", {})
        result = self._run_blender_action(action)
        self._update_context(action, result)
        return self._compact_result(result)

    def _run_blender_action(self, action: Mapping[str, Any]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="nodecue-sdk-tool-") as tmp:
            tmp_path = Path(tmp)
            action_path = tmp_path / "action.json"
            output_path = tmp_path / "output.json"
            script_path = tmp_path / "execute_action.py"
            action_path.write_text(json.dumps(action, ensure_ascii=False), encoding="utf-8")
            script_path.write_text(
                textwrap.dedent(
                    f"""
                    from __future__ import annotations
                    import json
                    import sys
                    from pathlib import Path

                    sys.path.insert(0, {str(self.root)!r})
                    for module_name in list(sys.modules):
                        if module_name == 'nodecue' or module_name.startswith('nodecue.'):
                            sys.modules.pop(module_name, None)
                    from nodecue.bpy_recipes import execute_action, json_safe

                    action = json.loads(Path({str(action_path)!r}).read_text(encoding='utf-8'))
                    result = execute_action(action)
                    import bpy
                    save_path = {str(self.blend_path)!r}
                    import tempfile
                    import os
                    save_dir = str(Path(save_path).parent)
                    save_stem = Path(save_path).stem
                    fd, tmp_save_path = tempfile.mkstemp(
                        prefix=save_stem + '.',
                        suffix='.tmp.blend',
                        dir=save_dir,
                    )
                    os.close(fd)
                    try:
                        Path(tmp_save_path).unlink(missing_ok=True)
                    except Exception:
                        pass
                    save_error = None
                    try:
                        bpy.ops.wm.save_as_mainfile(filepath=tmp_save_path, check_existing=False)
                        os.replace(tmp_save_path, save_path)
                    except Exception as exc:
                        save_error = str(exc)
                        try:
                            Path(tmp_save_path).unlink(missing_ok=True)
                        except Exception:
                            pass
                    if save_error:
                        if isinstance(result, dict):
                            result = dict(result)
                            result['save_error'] = save_error
                        else:
                            result = {{'result': result, 'save_error': save_error}}

                    Path({str(output_path)!r}).write_text(
                        json.dumps(json_safe(result), ensure_ascii=False, indent=2),
                        encoding='utf-8',
                    )
                    """
                ),
                encoding="utf-8",
            )
            cmd = list(self.blender_command)
            if self.blend_path.exists():
                cmd.extend(["-b", str(self.blend_path), "--python", str(script_path)])
            else:
                cmd.extend(["-b", "--python", str(script_path)])
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=str(self.root),
                timeout=self.timeout_seconds,
            )
            if proc.returncode != 0:
                return {
                    "error": "headless Blender action failed",
                    "returncode": proc.returncode,
                    "stderr": proc.stderr[-4000:],
                    "stdout": proc.stdout[-4000:],
                }
            if not output_path.exists():
                return {
                    "error": "headless Blender action produced no output",
                    "stderr": proc.stderr[-4000:],
                    "stdout": proc.stdout[-4000:],
                }
            return json.loads(output_path.read_text(encoding="utf-8"))

    def _compact_result(self, result: Any) -> dict[str, Any]:
        if not isinstance(result, Mapping):
            return {"result": json_safe(result)}
        if result.get("ok") and isinstance(result.get("data"), Mapping):
            return {"ok": True, "data": self._compact_readback(result["data"])}
        compact = json_safe(result)
        if isinstance(compact, dict) and isinstance(compact.get("node_groups"), list):
            compact["node_groups"] = compact["node_groups"][:50]
        if isinstance(compact, dict) and isinstance(compact.get("details"), dict):
            details = compact["details"]
            for key in ("available_from_outputs", "available_to_inputs", "available_inputs", "available_outputs"):
                if isinstance(details.get(key), list):
                    details[key] = details[key][:20]
        return compact

    def _compact_readback(self, readback: Mapping[str, Any]) -> dict[str, Any]:
        nodes = []
        raw_nodes = readback.get("nodes", [])
        if not isinstance(raw_nodes, list):
            raw_nodes = []
        for node in raw_nodes:
            if not isinstance(node, Mapping):
                continue
            raw_inputs = node.get("inputs", [])
            if not isinstance(raw_inputs, list):
                raw_inputs = []
            raw_outputs = node.get("outputs", [])
            if not isinstance(raw_outputs, list):
                raw_outputs = []
            nodes.append(
                {
                    "name": node.get("name"),
                    "label": node.get("label"),
                    "bl_idname": node.get("bl_idname"),
                    "location": node.get("location"),
                    "inputs": [
                        {
                            "name": socket.get("name"),
                            "identifier": socket.get("identifier"),
                            "type": socket.get("type"),
                            "is_linked": socket.get("is_linked"),
                        }
                        for socket in raw_inputs[:30]
                        if isinstance(socket, Mapping)
                    ],
                    "outputs": [
                        {
                            "name": socket.get("name"),
                            "identifier": socket.get("identifier"),
                            "type": socket.get("type"),
                            "is_linked": socket.get("is_linked"),
                        }
                        for socket in raw_outputs[:30]
                        if isinstance(socket, Mapping)
                    ],
                    "parent_frame": node.get("parent_frame"),
                }
            )
        return {
            "tree_name": readback.get("tree_name"),
            "active_node": readback.get("active_node"),
            "nodes": nodes,
            "links": readback.get("links") if isinstance(readback.get("links"), list) else [],
            "frames": readback.get("frames") if isinstance(readback.get("frames"), list) else [],
            "interface": readback.get("interface") or readback.get("interface_sockets") or [],
        }

    def _update_context(self, action: Mapping[str, Any], result: Mapping[str, Any]) -> None:
        action_type = action.get("type")
        params = action.get("parameters") if isinstance(action.get("parameters"), Mapping) else {}

        if action_type == "create_node_tree" and isinstance(result.get("tree_name"), str):
            self.current_tree_name = str(result["tree_name"])
        elif action_type == "read_active_node_tree" and result.get("ok"):
            data = result.get("data")
            if isinstance(data, Mapping) and isinstance(data.get("tree_name"), str):
                self.current_tree_name = str(data["tree_name"])

        if action_type in {"create_node", "append_asset_node_group"} and isinstance(result.get("node_name"), str):
            actual = str(result["node_name"])
            self.node_aliases[actual] = actual
            requested = params.get("alias") or params.get("name")
            if isinstance(requested, str) and requested.strip():
                self.node_aliases[requested] = actual
            group_name = params.get("group_name")
            if isinstance(group_name, str) and group_name.strip():
                self.node_aliases[group_name] = actual


def build_sdk_geometry_agent(skill: SkillBundle, session: HeadlessBlenderSession, provider: ProviderConfig):
    """Create the real NodeCue Geometry Agent with SDK function tools."""

    try:
        from agents import Agent, function_tool
    except Exception as exc:
        raise RuntimeError("Install openai-agents to run the SDK-backed agent") from exc

    model, model_settings = build_sdk_model(provider)

    @function_tool
    def list_skill_files() -> dict[str, Any]:
        """List readable files in the current Geometry Nodes skill package."""
        result = skill.list_files()
        call = {"tool_kind": "skill_tool", "tool": "list_skill_files", "result": result}
        session.skill_tool_calls.append(call)
        return json_safe(result)

    @function_tool
    def read_skill_file(
        path: Annotated[str, "Relative path inside the skill package, e.g. SKILL.md or patterns/surface-displacement.md"] = "SKILL.md",
        start_line: Annotated[int, "1-based start line"] = 1,
        max_lines: Annotated[int, "Maximum lines to return"] = 160,
    ) -> dict[str, Any]:
        """Read a bounded range from a skill file. Absolute paths and '..' are rejected."""
        try:
            already_read = set(session.skill_files_read)
            if not session.stage_results and path not in already_read and len(already_read) >= 4:
                result = {
                    "error": "Initial skill reading budget reached. Execute the first node stage now; read more skill files only after a stage fails or readback shows a specific gap.",
                    "path": path,
                    "files_read": sorted(already_read),
                }
                session.skill_tool_calls.append(
                    {
                        "tool_kind": "skill_tool",
                        "tool": "read_skill_file",
                        "path": path,
                        "start_line": start_line,
                        "max_lines": max_lines,
                        "result": result,
                    }
                )
                return json_safe(result)
            result = skill.read_file(path, start_line=start_line, max_lines=max_lines)
        except Exception as exc:
            result = {"error": str(exc), "path": path}
        if not result.get("error") and isinstance(result.get("path"), str):
            if result["path"] not in session.skill_files_read:
                session.skill_files_read.append(result["path"])
        session.skill_tool_calls.append(
            {
                "tool_kind": "skill_tool",
                "tool": "read_skill_file",
                "path": path,
                "start_line": start_line,
                "max_lines": max_lines,
                "result": {k: v for k, v in result.items() if k != "content"},
            }
        )
        return json_safe(result)

    @function_tool
    def search_skill(
        query: Annotated[str, "Keyword or phrase to search in the skill package"] = "",
        max_results: Annotated[int, "Maximum matches to return"] = 8,
        context_lines: Annotated[int, "Context lines around each match"] = 2,
    ) -> dict[str, Any]:
        """Search skill files and return matching paths, lines, and short context."""
        result = skill.search(query, max_results=max_results, context_lines=context_lines)
        if query and query not in session.skill_search_queries:
            session.skill_search_queries.append(query)
        session.skill_tool_calls.append(
            {
                "tool_kind": "skill_tool",
                "tool": "search_skill",
                "query": query,
                "max_results": max_results,
                "context_lines": context_lines,
                "result_count": len(result.get("matches", [])) if isinstance(result.get("matches"), list) else 0,
            }
        )
        return json_safe(result)

    def _parse_stage_value(value_json: str) -> Any:
        if value_json == "":
            return ""
        try:
            return json.loads(value_json)
        except Exception:
            return value_json

    def _parse_stage_socket_value(value_json: str, *, socket_type: str = "") -> Any:
        return coerce_stage_socket_value(_parse_stage_value(value_json), socket_type=socket_type)

    def _require_initial_skill_read(tool_name: str) -> dict[str, Any] | None:
        if session.skill_files_read:
            return None
        payload = {
            "tool_kind": "blender_tool",
            "tool": tool_name,
            "result": {
                "error": "Read SKILL.md with read_skill_file before using Blender tools. Then read more rule/pattern files only when the prompt or readback requires them.",
                "required_tool": "read_skill_file",
                "suggested_path": "SKILL.md",
            },
        }
        session.action_results.append(payload)
        return json_safe(payload)

    @function_tool
    def execute_node_stage(
        stage_goal: Annotated[str, "One concise goal for this execution stage"],
        create_tree_name: Annotated[str, "Optional new Geometry Nodes tree name for this stage"],
        tree_name: Annotated[str, "Existing tree name from readback; leave empty immediately after create_tree_name"],
        group_sockets: Annotated[list[StageGroupSocketSpec], "Group interface sockets to add before wiring"],
        nodes: Annotated[list[StageNodeSpec], "Nodes to create; each node must include exact bl_idname"],
        node_properties: Annotated[list[StageNodePropertySpec], "Node RNA properties to set, as JSON values"],
        socket_defaults: Annotated[list[StageSocketDefaultSpec], "Socket defaults to set, as JSON values"],
        links: Annotated[list[StageLinkSpec], "Links to create after nodes/properties/defaults"],
        frames: Annotated[list[StageFrameSpec], "Teaching frames to create or update"],
        arrange: Annotated[bool, "Arrange the tree after this stage"],
        readback_after: Annotated[bool, "Read the tree after the stage"],
        stop_on_error: Annotated[bool, "Stop the stage at the first failing action"],
    ) -> dict[str, Any]:
        """Execute a structured batch of safe node actions, then optionally read back the tree."""
        skill_error = _require_initial_skill_read("execute_node_stage")
        if skill_error is not None:
            return skill_error

        misuse_error = stage_node_property_misuse_error(node_properties)
        if misuse_error is not None:
            stage = {
                "tool_kind": "blender_tool",
                "stage_goal": stage_goal,
                "ok": False,
                "raw_action_count": 0,
                "failed_action": misuse_error,
                "results": [],
                "readback": None,
            }
            session.stage_results.append(stage)
            return json_safe(stage)

        actions: list[dict[str, Any]] = []
        if create_tree_name.strip():
            actions.append({"type": "create_node_tree", "parameters": {"name": create_tree_name.strip()}})
        for spec in group_sockets:
            params: dict[str, Any] = {
                "tree_name": tree_name,
                "name": spec.name,
                "socket_type": spec.socket_type,
                "in_out": spec.in_out,
            }
            if spec.default_value_json != "":
                params["default_value"] = _parse_stage_socket_value(
                    spec.default_value_json,
                    socket_type=spec.socket_type,
                )
            actions.append({"type": "add_group_socket", "parameters": params})
        for spec in nodes:
            actions.append(
                {
                    "type": "create_node",
                    "parameters": {
                        "tree_name": tree_name,
                        "bl_idname": spec.bl_idname,
                        "alias": spec.name,
                        "location_x": spec.location_x,
                        "location_y": spec.location_y,
                    },
                }
            )
        for spec in node_properties:
            actions.append(
                {
                    "type": "set_node_property",
                    "parameters": {
                        "tree_name": tree_name,
                        "node_name": spec.node_name,
                        "property_name": spec.property_name,
                        "value": _parse_stage_value(spec.value_json),
                    },
                }
            )
        for spec in socket_defaults:
            actions.append(
                {
                    "type": "set_socket_default",
                    "parameters": {
                        "tree_name": tree_name,
                        "node_name": spec.node_name,
                        "socket_name": spec.socket_name,
                        "value": _parse_stage_socket_value(spec.value_json),
                    },
                }
            )
        for spec in links:
            actions.append(
                {
                    "type": "connect",
                    "parameters": {
                        "tree_name": tree_name,
                        "from_node": spec.from_node,
                        "from_socket": spec.from_socket,
                        "to_node": spec.to_node,
                        "to_socket": spec.to_socket,
                    },
                }
            )
        for spec in frames:
            actions.append(
                {
                    "type": "add_frame",
                    "parameters": {
                        "tree_name": tree_name,
                        "node_names": list(spec.node_names),
                        "label": spec.label,
                        "frame_name": spec.frame_name,
                    },
                }
            )
        arrange_warning = ""
        if arrange:
            if not should_skip_stage_arrange(len(actions)):
                actions.append({"type": "arrange_nodes", "parameters": {"tree_name": tree_name}})
            else:
                arrange_warning = "arrange skipped for this large stage; use explicit node locations and frames, or arrange after a smaller verified stage."
        if not actions:
            return {"error": "execute_node_stage requires at least one structured action"}
        result = session.execute_stage(
            stage_goal,
            actions,
            readback_after=readback_after,
            stop_on_error=stop_on_error,
        )
        if arrange_warning:
            result.setdefault("warnings", []).append(arrange_warning)
            if session.stage_results:
                session.stage_results[-1].setdefault("warnings", []).append(arrange_warning)
        return result

    @function_tool
    def create_node_tree(name: Annotated[str, "Geometry Nodes tree name"] = "NodeCue") -> dict[str, Any]:
        """Create a Geometry Nodes tree and return the actual tree name."""
        return session.execute("create_node_tree", {"name": name})

    @function_tool
    def read_active_node_tree() -> dict[str, Any]:
        """Read the active Geometry Nodes tree, nodes, sockets, links, and frames."""
        skill_error = _require_initial_skill_read("read_active_node_tree")
        if skill_error is not None:
            return skill_error
        return session.read_active_node_tree()

    @function_tool
    def create_node(
        tree_name: Annotated[str, "Actual tree name returned by create_node_tree or readback"] = "",
        bl_idname: Annotated[str, "Exact Blender node bl_idname"] = "",
        name: Annotated[str, "Optional requested node name"] = "",
        label: Annotated[str, "Optional teaching label"] = "",
        location_x: Annotated[float, "Node editor x location"] = 0.0,
        location_y: Annotated[float, "Node editor y location"] = 0.0,
    ) -> dict[str, Any]:
        """Create one node by exact bl_idname."""
        return session.execute(
            "create_node",
            {
                "tree_name": tree_name,
                "bl_idname": bl_idname,
                "name": name,
                "label": label,
                "location_x": location_x,
                "location_y": location_y,
            },
        )

    @function_tool
    def connect(
        tree_name: Annotated[str, "Actual tree name"] = "",
        from_node: Annotated[str, "Source node name from readback"] = "",
        from_socket: Annotated[str, "Source socket name or identifier"] = "",
        to_node: Annotated[str, "Target node name from readback"] = "",
        to_socket: Annotated[str, "Target socket name or identifier"] = "",
    ) -> dict[str, Any]:
        """Connect one output socket to one input socket."""
        return session.execute(
            "connect",
            {
                "tree_name": tree_name,
                "from_node": from_node,
                "from_socket": from_socket,
                "to_node": to_node,
                "to_socket": to_socket,
            },
        )

    @function_tool
    def set_socket_default(
        tree_name: Annotated[str, "Actual tree name"] = "",
        node_name: Annotated[str, "Node name from readback"] = "",
        socket_name: Annotated[str, "Socket name or identifier"] = "",
        value: Annotated[str, "JSON scalar or array value"] = "",
    ) -> dict[str, Any]:
        """Set a socket default value; pass arrays or booleans as JSON strings."""
        try:
            parsed_value = json.loads(value)
        except Exception:
            parsed_value = value
        return session.execute(
            "set_socket_default",
            {
                "tree_name": tree_name,
                "node_name": node_name,
                "socket_name": socket_name,
                "value": parsed_value,
            },
        )

    @function_tool
    def set_node_property(
        tree_name: Annotated[str, "Actual tree name"] = "",
        node_name: Annotated[str, "Node name from readback"] = "",
        property_name: Annotated[str, "Writable RNA property identifier"] = "",
        value: Annotated[str, "JSON scalar or array value"] = "",
    ) -> dict[str, Any]:
        """Set a node RNA property by exact property identifier."""
        try:
            parsed_value = json.loads(value)
        except Exception:
            parsed_value = value
        return session.execute(
            "set_node_property",
            {
                "tree_name": tree_name,
                "node_name": node_name,
                "property_name": property_name,
                "value": parsed_value,
            },
        )

    @function_tool
    def add_frame(
        tree_name: Annotated[str, "Actual tree name"] = "",
        node_names: Annotated[list[str], "Node names to parent under the frame"] = (),
        label: Annotated[str, "Frame label explaining this graph region"] = "",
        frame_name: Annotated[str, "Optional existing frame node name to update"] = "",
    ) -> dict[str, Any]:
        """Create or update a teaching frame and parent existing nodes under it."""
        return session.execute(
            "add_frame",
            {
                "tree_name": tree_name,
                "node_names": list(node_names),
                "label": label,
                "frame_name": frame_name,
            },
        )

    @function_tool
    def add_group_socket(
        tree_name: Annotated[str, "Actual tree name"] = "",
        name: Annotated[str, "Group interface socket label"] = "",
        socket_type: Annotated[
            str,
            "Blender socket type, e.g. NodeSocketFloat, NodeSocketInt, NodeSocketBool, NodeSocketVector, NodeSocketGeometry",
        ] = "NodeSocketFloat",
        in_out: Annotated[str, "INPUT or OUTPUT"] = "INPUT",
        default_value: Annotated[str, "Optional JSON scalar or array default value"] = "",
    ) -> dict[str, Any]:
        """Add a group interface socket for user-facing controls or outputs."""
        params: dict[str, Any] = {
            "tree_name": tree_name,
            "name": name,
            "socket_type": socket_type,
            "in_out": in_out,
        }
        if default_value != "":
            try:
                params["default_value"] = json.loads(default_value)
            except Exception:
                params["default_value"] = default_value
        return session.execute("add_group_socket", params)

    @function_tool
    def list_asset_node_groups(
        source: Annotated[str, "Asset source: all, essentials, or user"] = "all",
    ) -> dict[str, Any]:
        """List authorized Blender asset-library node groups for possible reuse."""
        skill_error = _require_initial_skill_read("list_asset_node_groups")
        if skill_error is not None:
            return skill_error
        return session.execute("list_asset_node_groups", {"source": source})

    @function_tool
    def append_asset_node_group(
        source_file: Annotated[str, "Blend file path returned by list_asset_node_groups"] = "",
        group_name: Annotated[str, "Node group name returned by list_asset_node_groups"] = "",
        tree_name: Annotated[str, "Optional current tree to insert a GeometryNodeGroup into"] = "",
    ) -> dict[str, Any]:
        """Append an authorized node group asset and optionally insert it into the current tree."""
        return session.execute(
            "append_asset_node_group",
            {
                "source_file": source_file,
                "group_name": group_name,
                "tree_name": tree_name,
            },
        )

    @function_tool
    def arrange_nodes(tree_name: Annotated[str, "Actual tree name"] = "") -> dict[str, Any]:
        """Auto-arrange the current node tree for readability."""
        return session.execute("arrange_nodes", {"tree_name": tree_name})

    base_prompt = skill.system_prompt.strip() or (
        "You are a Blender Geometry Nodes builder. Read relevant skill files, "
        "build in stages, verify readback, and explain the resulting node tree."
    )
    runtime_instructions = "\n".join(
        [
            "NodeCue runtime:",
            "- You have skill tools for reading the Geometry Nodes skill package and Blender tools for safe node edits.",
            "- Before using Blender tools in any mode, read SKILL.md with read_skill_file.",
            "- Before Generate or Modify work, also inspect at least one relevant rule or pattern file with the skill tools.",
            "- Initial skill lookup budget: SKILL.md plus at most three relevant rule/pattern files before the first execute_node_stage call.",
            "- Do not assume hidden injected skill text; use list_skill_files, search_skill, and read_skill_file when you need node guidance.",
            "- Blender execution tools are limited to node-related operations. Never emit or request arbitrary Python.",
            f"- The supported stage action types are: {', '.join(supported_action_types())}.",
            "- Use execute_node_stage for all Blender writes. Fill its structured fields directly instead of writing raw Python or free-form plans.",
            "- A stage should contain a small coherent batch of safe NodeCue actions and should read back after execution.",
            "- In Generate mode, never submit a stage that only creates or reads the node tree; include actual content nodes and links in the first write stage.",
            "- For a new generated graph, set create_tree_name and include the first content nodes in the same execute_node_stage call.",
            "- Do not rename Blender nodes and do not set ordinary node labels. Use node names only as temporary aliases for tool references; put explanations on frames.",
            "- Use socket_defaults for every socket default value. Never put inputs[], outputs[], or default_value in node_properties.",
            "- Use node_properties only for real node RNA properties such as operation, data_type, mode, or domain.",
            "- Use value_json/default_value_json for values such as 2.0, true, or [0,0,1].",
            "- Use exact tree names, node names, socket names, and identifiers returned by tools. Blender may rename nodes.",
            "- If a stage fails, repair from the returned readback/details instead of repeating the same action.",
        ]
    )
    instructions = "\n\n".join([base_prompt, runtime_instructions])
    return Agent(
        name="NodeCue Geometry Agent",
        instructions=instructions,
        tools=[
            list_skill_files,
            read_skill_file,
            search_skill,
            execute_node_stage,
            read_active_node_tree,
            list_asset_node_groups,
        ],
        model=model,
        model_settings=model_settings,
    )


async def run_sdk_geometry_agent(
    *,
    prompt: str,
    mode: AgentMode,
    skill_path: str | Path,
    provider: ProviderConfig,
    blend_path: str | Path,
    max_turns: int = 20,
) -> dict[str, Any]:
    try:
        from agents import Runner
    except Exception as exc:
        raise RuntimeError("Install openai-agents to run the SDK-backed agent") from exc

    skill = SkillBundle.load(skill_path)
    session = HeadlessBlenderSession(
        blend_path,
        root=Path(skill_path).resolve().parents[2],
        timeout_seconds=provider.timeout_seconds,
    )
    session.mode = mode
    agent = build_sdk_geometry_agent(skill, session, provider)
    user_input = f"Mode: {mode}\nPrompt: {prompt}"
    run_error = None
    result = None
    try:
        result = await asyncio.wait_for(
            Runner.run(agent, user_input, max_turns=max_turns),
            timeout=provider.timeout_seconds,
        )
    except Exception as exc:
        run_error = str(exc)

    readback_result = session.final_readback()
    readback = readback_result
    if isinstance(readback, Mapping) and readback.get("ok"):
        readback = readback.get("data")

    return {
        "error": run_error,
        "final_output": str(result.final_output) if result is not None else "",
        "action_results": session.action_results,
        "stage_results": session.stage_results,
        "skill_tool_calls": session.skill_tool_calls,
        "skill_files_read": session.skill_files_read,
        "skill_search_queries": session.skill_search_queries,
        "readback": readback,
        "blend_path": str(session.blend_path),
        "new_items": [
            {"type": type(item).__name__, "repr": repr(item)[:1000]}
            for item in getattr(result, "new_items", []) if result is not None
        ],
        "raw_responses": [
            {
                "type": type(response).__name__,
                "usage": json_safe(getattr(response, "usage", None)),
                "repr": repr(response)[:1000],
            }
            for response in getattr(result, "raw_responses", []) if result is not None
        ],
    }


class SocketBlenderSession:
    """Execute NodeCue actions through the addon's main-thread socket bridge."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9877, *, timeout_seconds: int = 120):
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds
        self.current_tree_name = ""
        self.node_aliases: dict[str, str] = {}
        self.action_results: list[dict[str, Any]] = []
        self.stage_results: list[dict[str, Any]] = []
        self.skill_tool_calls: list[dict[str, Any]] = []
        self.skill_files_read: list[str] = []
        self.skill_search_queries: list[str] = []
        self.mode: AgentMode | str = ""

    def _map_node_name(self, name: Any) -> Any:
        if isinstance(name, str):
            return self.node_aliases.get(name, name)
        return name

    def _prepare_action(self, action_type: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
        prepared = normalize_action({"type": action_type, "parameters": parameters})
        params = dict(prepared["parameters"])
        if prepared["type"] not in {"create_node_tree", "read_active_node_tree", "list_asset_node_groups"}:
            if not params.get("tree_name"):
                params["tree_name"] = self.current_tree_name

        for key in ("from_node", "to_node", "node_name"):
            if key in params:
                params[key] = self._map_node_name(params[key])
        if isinstance(params.get("node_names"), list):
            params["node_names"] = [self._map_node_name(name) for name in params["node_names"]]

        prepared["parameters"] = params
        return prepared

    def execute(self, action_type: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
        action = self._prepare_action(action_type, parameters)
        result = self._send_action(action)
        compact_result = self._compact_result(result)
        self._update_context(action, compact_result)
        payload = {"tool_kind": "blender_tool", "action": action, "result": compact_result}
        self.action_results.append(payload)
        return json_safe(payload)

    def execute_stage(
        self,
        stage_goal: str,
        actions: list[Mapping[str, Any]],
        *,
        readback_after: bool = True,
        stop_on_error: bool = True,
    ) -> dict[str, Any]:
        raw_results: list[dict[str, Any]] = []
        failed_action: dict[str, Any] | None = None
        action_types = {
            str(action.get("type") or action.get("action") or "")
            for action in actions
            if isinstance(action, Mapping)
        }
        if self.mode == "generate" and not (action_types & {"create_node", "connect", "append_asset_node_group"}):
            stage = {
                "tool_kind": "blender_tool",
                "stage_goal": stage_goal,
                "ok": False,
                "raw_action_count": 0,
                "failed_action": {
                    "error": "Generate stages must include content node creation, asset insertion, or links; do not submit a create_node_tree-only stage.",
                    "action_types": sorted(action_types),
                },
                "results": [],
                "readback": None,
            }
            self.stage_results.append(stage)
            return json_safe(stage)
        for raw_action in actions:
            try:
                action_type = str(raw_action.get("type") or raw_action.get("action") or "")
                raw_params = raw_action.get("parameters") or raw_action.get("params") or {}
                if not isinstance(raw_params, Mapping):
                    raise ValueError("action parameters must be an object")
                action = self._prepare_action(action_type, raw_params)
            except Exception as exc:
                failed_action = {"raw_action": json_safe(raw_action), "error": str(exc)}
                raw_results.append({"tool_kind": "blender_tool", "error": str(exc), "raw_action": json_safe(raw_action)})
                if stop_on_error:
                    break
                continue

            result = self._send_action(action)
            compact_result = self._compact_result(result)
            self._update_context(action, compact_result)
            payload = {"tool_kind": "blender_tool", "action": action, "result": compact_result}
            self.action_results.append(payload)
            raw_results.append(payload)
            if isinstance(compact_result, Mapping) and compact_result.get("error"):
                failed_action = payload
                if stop_on_error:
                    break

        readback = self.final_readback() if readback_after else None
        stage = {
            "tool_kind": "blender_tool",
            "stage_goal": stage_goal,
            "ok": failed_action is None,
            "raw_action_count": len(raw_results),
            "failed_action": failed_action,
            "results": raw_results,
            "readback": readback,
        }
        self.stage_results.append(stage)
        return json_safe(stage)

    def read_active_node_tree(self) -> dict[str, Any]:
        return self.execute("read_active_node_tree", {})

    def final_readback(self) -> dict[str, Any]:
        action = self._prepare_action("read_active_node_tree", {})
        result = self._send_action(action)
        compact = self._compact_result(result)
        self._update_context(action, compact)
        return compact

    def _send_action(self, action: Mapping[str, Any]) -> dict[str, Any]:
        command = ACTION_TO_COMMAND[str(action["type"])]
        payload = {"type": command, "params": dict(action.get("parameters") or {})}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        with socket.create_connection((self.host, self.port), timeout=self.timeout_seconds) as sock:
            sock.settimeout(self.timeout_seconds)
            sock.sendall(struct.pack("!I", len(body)) + body)
            header = self._recv_exact(sock, 4)
            if not header:
                return {"error": "NodeCue bridge returned no response"}
            (length,) = struct.unpack("!I", header)
            response_body = self._recv_exact(sock, length)
        if not response_body:
            return {"error": "NodeCue bridge returned an empty response body"}
        response = json.loads(response_body.decode("utf-8"))
        if response.get("status") == "success":
            return response.get("result") or {}
        result = response.get("result")
        if isinstance(result, dict):
            return result
        return {"error": json.dumps(response, ensure_ascii=False)}

    @staticmethod
    def _recv_exact(sock: socket.socket, length: int) -> bytes:
        data = b""
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                break
            data += chunk
        return data

    def _compact_result(self, result: Any) -> dict[str, Any]:
        return HeadlessBlenderSession._compact_result(self, result)

    def _compact_readback(self, readback: Mapping[str, Any]) -> dict[str, Any]:
        return HeadlessBlenderSession._compact_readback(self, readback)

    def _update_context(self, action: Mapping[str, Any], result: Mapping[str, Any]) -> None:
        HeadlessBlenderSession._update_context(self, action, result)


async def run_sdk_geometry_agent_on_socket(
    *,
    prompt: str,
    mode: AgentMode,
    skill_path: str | Path,
    provider: ProviderConfig,
    host: str = "127.0.0.1",
    port: int = 9877,
    max_turns: int = 35,
) -> dict[str, Any]:
    try:
        from agents import Runner
    except Exception as exc:
        raise RuntimeError("Install openai-agents to run the SDK-backed agent") from exc

    skill = SkillBundle.load(skill_path)
    session = SocketBlenderSession(host=host, port=port, timeout_seconds=provider.timeout_seconds)
    session.mode = mode
    agent = build_sdk_geometry_agent(skill, session, provider)
    user_input = f"Mode: {mode}\nPrompt: {prompt}"

    run_error = None
    result = None
    try:
        result = await asyncio.wait_for(
            Runner.run(agent, user_input, max_turns=max_turns),
            timeout=provider.timeout_seconds,
        )
    except Exception as exc:
        run_error = str(exc)

    readback_result = session.final_readback()
    readback = readback_result
    if isinstance(readback, Mapping) and readback.get("ok"):
        readback = readback.get("data")

    return {
        "error": run_error,
        "final_output": str(result.final_output) if result is not None else "",
        "action_results": session.action_results,
        "stage_results": session.stage_results,
        "skill_tool_calls": session.skill_tool_calls,
        "skill_files_read": session.skill_files_read,
        "skill_search_queries": session.skill_search_queries,
        "readback": readback,
        "new_items": [
            {"type": type(item).__name__, "repr": repr(item)[:1000]}
            for item in getattr(result, "new_items", []) if result is not None
        ],
        "raw_responses": [
            {
                "type": type(response).__name__,
                "usage": json_safe(getattr(response, "usage", None)),
                "repr": repr(response)[:1000],
            }
            for response in getattr(result, "raw_responses", []) if result is not None
        ],
    }


def build_geometry_agent(skill: SkillBundle, bridge: MockBlenderBridge):
    """Create a real OpenAI Agents SDK agent when the SDK is installed."""

    try:
        from agents import Agent, function_tool
    except Exception as exc:
        raise RuntimeError("Install openai-agents to run the SDK-backed agent") from exc

    @function_tool
    def read_active_node_tree() -> dict[str, Any]:
        """Read the active Blender node tree through the bridge."""
        return bridge.read_active_node_tree()

    @function_tool
    def create_node_tree(name: str = "NodeCue") -> dict[str, Any]:
        """Create a Geometry Nodes tree through the bridge."""
        return bridge.create_node_tree(name)

    instructions = "\n\n".join(
        [
            "You are NodeCue Geometry Agent. Build teachable Blender Geometry Nodes graphs.",
            "Use tools for Blender state and execution. Explain what each result does.",
            skill.instruction_excerpt(limit=6000),
        ]
    )
    return Agent(
        name="NodeCue Geometry Agent",
        instructions=instructions,
        tools=[read_active_node_tree, create_node_tree],
    )


def _provider_api_key(provider: ProviderConfig) -> str:
    api_key_env = provider.resolved_api_key_env()
    api_key = os.environ.get(api_key_env, "").strip() if api_key_env else ""
    if provider.requires_api_key and not api_key:
        raise RuntimeError(f"missing API key env var: {api_key_env}")
    return api_key


def _extract_openai_compatible_text(payload: dict[str, Any]) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"provider response missing message content: {payload}") from exc
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, dict) and isinstance(item.get("content"), str):
                parts.append(item["content"])
        if parts:
            return "".join(parts)
    raise RuntimeError(f"provider response content was not a supported text shape: {content!r}")


def _openai_compatible_chat_completion(
    *,
    messages: list[dict[str, str]],
    provider: ProviderConfig,
    timeout_seconds: int = 120,
    max_tokens: int = 800,
) -> str:
    api_key = _provider_api_key(provider)
    if not provider.model:
        raise RuntimeError("missing NODECUE_AGENT_MODEL")

    base_url = provider.resolved_base_url()
    body = {
        "model": provider.model,
        "messages": messages,
        "temperature": provider.temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if provider.kind == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/NodeCue/NodeCue"
        headers["X-Title"] = "NodeCue Agent Eval"

    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"provider request failed HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"provider request failed: {exc}") from exc

    return _extract_openai_compatible_text(payload)


def _anthropic_compatible_chat_completion(
    *,
    messages: list[dict[str, str]],
    provider: ProviderConfig,
    timeout_seconds: int = 120,
    max_tokens: int = 800,
) -> str:
    api_key = _provider_api_key(provider)
    if not provider.model:
        raise RuntimeError("missing NODECUE_AGENT_MODEL")

    system_parts: list[str] = []
    anthropic_messages: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            system_parts.append(content)
        elif role in {"user", "assistant"}:
            anthropic_messages.append({"role": role, "content": content})
        else:
            anthropic_messages.append({"role": "user", "content": content})
    if not anthropic_messages:
        anthropic_messages.append({"role": "user", "content": ""})

    body: dict[str, Any] = {
        "model": provider.model,
        "messages": anthropic_messages,
        "max_tokens": max_tokens,
        "temperature": provider.temperature,
    }
    if system_parts:
        body["system"] = "\n\n".join(system_parts)

    headers = {
        "Content-Type": "application/json",
        "anthropic-version": ANTHROPIC_VERSION,
    }
    if api_key:
        headers["x-api-key"] = api_key

    request = urllib.request.Request(
        f"{provider.resolved_base_url()}/messages",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"provider request failed HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"provider request failed: {exc}") from exc

    content = payload.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        if parts:
            return "".join(parts)
    raise RuntimeError(f"provider response content was not a supported text shape: {content!r}")


def _model_chat_completion(
    *,
    messages: list[dict[str, str]],
    provider: ProviderConfig,
    timeout_seconds: int | None = None,
    max_tokens: int = 800,
) -> str:
    timeout = timeout_seconds or provider.timeout_seconds
    if provider.kind in {"openai", "openai-compatible", "openrouter"}:
        return _openai_compatible_chat_completion(
            messages=messages,
            provider=provider,
            timeout_seconds=timeout,
            max_tokens=max_tokens,
        )
    if provider.kind in {"anthropic", "anthropic-compatible"}:
        return _anthropic_compatible_chat_completion(
            messages=messages,
            provider=provider,
            timeout_seconds=timeout,
            max_tokens=max_tokens,
        )
    raise RuntimeError(f"unsupported real provider: {provider.kind}")


def _openrouter_chat_completion(
    *,
    messages: list[dict[str, str]],
    provider: ProviderConfig,
    timeout_seconds: int = 120,
    max_tokens: int = 800,
) -> str:
    return _openai_compatible_chat_completion(
        messages=messages,
        provider=provider,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
    )


def _planning_messages(prompt: str, skill: SkillBundle, archetype_context: str) -> list[dict[str, str]]:
    instructions = "\n\n".join(
        [
            "You are NodeCue Geometry Agent evaluating a Blender Geometry Nodes request.",
            "Return strict JSON only. Do not include markdown fences or prose outside JSON.",
            "JSON schema: {\"primary_archetype\":\"A1|A2|A3|A4|A5|A7|A8|A9\", \"bl_idnames\":[\"...\"], \"rationale\":\"...\", \"confidence\":0.0}",
            "Choose the most likely archetype and list the minimum Blender node bl_idnames needed to implement the user's request.",
            "Use exact Geometry Nodes / ShaderNode / FunctionNode bl_idnames. Do not invent node identifiers.",
            "You are not given expected labels. Judge only from the user prompt and skill guidance.",
            "Archetype reference:",
            archetype_context.strip() or "(No external archetype reference provided.)",
            "Skill excerpt:",
            skill.instruction_excerpt(limit=8000),
        ]
    )
    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": prompt},
    ]


def _action_planning_messages(prompt: str, mode: AgentMode, skill: SkillBundle) -> list[dict[str, str]]:
    supported = ", ".join(supported_action_types())
    instructions = "\n\n".join(
        [
            "You are NodeCue's internal node-system planner.",
            "Return strict JSON only. Do not include markdown fences or prose outside JSON.",
            "Plan only Blender node-related work. Do not emit arbitrary Python.",
            "Output schema: {\"mode\":\"generate|explain|modify\", \"slices\":[{\"intent\":\"...\", \"actions\":[{\"type\":\"...\", \"intent\":\"...\", \"parameters\":{}, \"expected_readback\":{}, \"failure_recovery\":\"...\"}]}], \"final_explanation_goal\":\"...\"}",
            f"Supported action types: {supported}.",
            "Use slices of 1-3 actions, then include a readback action when the slice changes Blender state.",
            "Use asset actions only when reuse is materially better than rebuilding from primitive nodes.",
            "Skill excerpt:",
            skill.instruction_excerpt(limit=10000),
        ]
    )
    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": f"Mode: {mode}\nPrompt: {prompt}"},
    ]


def plan_geometry_prompt(
    prompt: str,
    skill_path: str | Path,
    *,
    provider: ProviderConfig | None = None,
    archetype_context: str = "",
    timeout_seconds: int = 120,
) -> AgentPlan:
    active_provider = provider or ProviderConfig.from_env()
    if active_provider.kind == "mock":
        return AgentPlan(
            primary_archetype="UNKNOWN",
            bl_idnames=[],
            rationale="Mock provider does not call a real model.",
            confidence=0.0,
        )

    skill = SkillBundle.load(skill_path)
    raw = _model_chat_completion(
        messages=_planning_messages(prompt, skill, archetype_context),
        provider=active_provider,
        timeout_seconds=timeout_seconds,
    )
    return AgentPlan.from_json_text(raw)


def plan_nodecue_actions(
    prompt: str,
    mode: AgentMode,
    skill_path: str | Path,
    *,
    provider: ProviderConfig | None = None,
    timeout_seconds: int = 120,
) -> NodeCueActionPlan:
    active_provider = provider or ProviderConfig.from_env()
    if active_provider.kind == "mock":
        if mode == "explain":
            return NodeCueActionPlan(
                mode=mode,
                slices=[
                    ActionSlice(
                        intent="Read the active node tree before explaining it.",
                        actions=[
                            NodeCueAction(
                                type="read_active_node_tree",
                                intent="Inspect the active node tree.",
                                parameters={},
                                expected_readback={"ok": True},
                                failure_recovery="Ask the user to select an object with a node modifier.",
                            )
                        ],
                    )
                ],
                final_explanation_goal="Explain the active node tree in teachable terms.",
            )
        return NodeCueActionPlan(
            mode=mode,
            slices=[
                ActionSlice(
                    intent="Create a new node tree shell.",
                    actions=[
                        NodeCueAction(
                            type="create_node_tree",
                            intent="Create a Geometry Nodes tree for the request.",
                            parameters={"name": "NodeCue"},
                            expected_readback={"tree_name": "NodeCue"},
                            failure_recovery="Ask the user to select a mesh object if creation fails.",
                        ),
                        NodeCueAction(
                            type="read_active_node_tree",
                            intent="Read back the created tree.",
                            parameters={},
                            expected_readback={"ok": True},
                            failure_recovery="Retry with an explicit tree name.",
                        ),
                    ],
                )
            ],
            final_explanation_goal="Explain the generated graph and the next implementation slice.",
        )

    skill = SkillBundle.load(skill_path)
    raw = _model_chat_completion(
        messages=_action_planning_messages(prompt, mode, skill),
        provider=active_provider,
        timeout_seconds=timeout_seconds,
    )
    return NodeCueActionPlan.from_json_text(raw)


async def run_with_agents_sdk(
    request: AgentRequest,
    *,
    bridge: MockBlenderBridge | None = None,
    session_db: str | Path = "nodecue-agent-sessions.sqlite",
) -> str:
    """Run the prototype with OpenAI Agents SDK.

    This is deliberately opt-in so the addon can boot without SDK dependencies.
    """

    try:
        from agents import RunConfig, Runner, SQLiteSession
    except Exception as exc:
        raise RuntimeError("Install openai-agents to run the SDK-backed agent") from exc

    skill = SkillBundle.load(request.skill_path)
    active_bridge = bridge or MockBlenderBridge()
    agent = build_geometry_agent(skill, active_bridge)
    session = SQLiteSession("nodecue-geometry", str(Path(session_db).expanduser()))
    run_config = RunConfig(model=request.provider.model or None)
    result = await Runner.run(agent, request.prompt, session=session, run_config=run_config)
    return str(result.final_output)


def run_prototype(
    prompt: str,
    mode: AgentMode,
    skill_path: str | Path,
    *,
    provider_kind: ProviderKind = "mock",
    model: str = "",
    base_url: str = "",
    api_key_env: str = "",
    on_event: Callable[[StreamEvent], None] | None = None,
) -> list[StreamEvent]:
    request = AgentRequest(
        prompt=prompt,
        mode=mode,
        skill_path=str(skill_path),
        provider=ProviderConfig(
            kind=provider_kind,
            model=model,
            base_url=base_url,
            api_key_env=api_key_env,
        ),
    )
    events = list(NodeCueAgentRunner().stream(request))
    if on_event:
        for event in events:
            on_event(event)
    return events
