from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime

import bpy

from nodecue import deps as agent_deps
from nodecue.agent_env import compose_sidecar_env, load_env_values, resolved_api_key


DEFAULT_SKILL_PATH = str(Path(__file__).resolve().parent / "skills" / "geometry-nodes")


def _default_sidecar_root() -> str:
    env_root = os.environ.get("NODECUE_REPO_ROOT", "").strip()
    if env_root and (Path(env_root).expanduser() / "nodecue_agent").exists():
        return env_root
    for parent in Path(__file__).resolve().parents:
        if (parent / "nodecue_agent").exists():
            return str(parent)
    return str(Path(__file__).resolve().parents[1])


def _user_scripts_dir() -> str:
    try:
        return bpy.utils.user_resource("SCRIPTS") or ""
    except Exception:
        return ""


def _deps_dir() -> Path:
    return agent_deps.deps_dir(_user_scripts_dir() or None)


def _sidecar_pythonpath(sidecar_root: Path | str) -> str:
    root = Path(sidecar_root).expanduser()
    paths = [str(root)]
    if str(root.parent) not in paths:
        paths.append(str(root.parent))
    dep_dir = _deps_dir()
    if dep_dir.is_dir():
        paths.append(str(dep_dir))
    return os.pathsep.join(paths)


def _default_agent_python() -> str:
    env_python = os.environ.get("NODECUE_AGENT_PYTHON", "").strip()
    if env_python and Path(env_python).expanduser().exists():
        return env_python
    return sys.executable


def _default_env_file() -> str:
    env_file = Path(_default_sidecar_root()) / ".env"
    return str(env_file)


_AGENT_PROCESS: subprocess.Popen | None = None
_AGENT_REPORT_PATH: Path | None = None
_AGENT_STDERR_PATH: Path | None = None
_AGENT_ARTIFACT_DIR: Path | None = None
_AGENT_CANCEL_REQUESTED = False
_DEPS_PROCESS: subprocess.Popen | None = None
_DEPS_LOG_PATH: Path | None = None


def _default_artifact_root() -> str:
    root = Path(_default_sidecar_root())
    if (root / "tests").exists():
        return str(root / "tests" / "integration" / "debug_blends" / "nodecue_plugin_runs")
    scripts_dir = _user_scripts_dir()
    if scripts_dir:
        # Stable, user-findable location; temp dirs get cleaned by the OS.
        return str(Path(scripts_dir) / "nodecue-runs")
    return str(Path(tempfile.gettempdir()) / "nodecue_plugin_agent")


def _apply_model_preset(self, context):
    if self.agent_model_preset != "custom":
        self.agent_model = self.agent_model_preset


_load_env_values = load_env_values


def _resolved_api_key_env(provider: str, explicit: str) -> str:
    if explicit:
        return explicit
    if provider == "openrouter":
        return "OPENROUTER_API_KEY"
    if provider == "openai":
        return "OPENAI_API_KEY"
    if provider in {"anthropic", "anthropic-compatible"}:
        return "ANTHROPIC_API_KEY"
    return ""


def _provider_requires_api_key(provider: str) -> bool:
    return provider in {"openrouter", "openai", "anthropic"}


def _sanitize_artifact_part(value: str) -> str:
    cleaned = [ch if ch.isalnum() or ch in "-_." else "_" for ch in value.strip()]
    return "".join(cleaned).strip("_") or "model"


class GN_AI_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    # --- NodeCue Agent ---
    agent_provider: bpy.props.EnumProperty(
        name="Provider",
        items=(
            ("openai", "OpenAI", "Use OpenAI through the Agents SDK"),
            ("anthropic", "Anthropic", "Use Anthropic's API"),
            (
                "anthropic-compatible",
                "Anthropic Compatible",
                "Use an Anthropic-compatible endpoint",
            ),
            ("openrouter", "OpenRouter", "Use OpenRouter's OpenAI-compatible API"),
            (
                "openai-compatible",
                "OpenAI Compatible",
                "Use a local or third-party OpenAI-compatible endpoint",
            ),
        ),
        default="openrouter",
    )
    agent_model_preset: bpy.props.EnumProperty(
        name="Recommended",
        description=(
            "Models verified with NodeCue's Geometry Nodes evals; "
            "picking one fills the Model field, or choose Custom and type any model id"
        ),
        items=(
            ("custom", "Custom (type below)", "Type any provider model id in the Model field"),
            (
                "moonshotai/kimi-k2.6",
                "Kimi K2.6",
                "Verified with NodeCue Geometry Nodes evals",
            ),
            (
                "deepseek/deepseek-v4-pro",
                "DeepSeek V4 Pro",
                "Verified with NodeCue Geometry Nodes evals",
            ),
        ),
        default="custom",
        update=_apply_model_preset,
    )
    agent_model: bpy.props.StringProperty(
        name="Model",
        default="",
        description="Model id for the selected provider",
    )
    agent_base_url: bpy.props.StringProperty(
        name="Base URL",
        default="",
        description="Optional OpenAI-compatible API base URL",
    )
    agent_api_key: bpy.props.StringProperty(
        name="API Key",
        default="",
        subtype="PASSWORD",
        description=(
            "Provider API key. Stored in Blender's preferences file in plain text; "
            "prefer the Env File option in Advanced if you manage secrets in files. "
            "Ignored when the key is already set in the OS environment"
        ),
    )
    agent_api_key_env: bpy.props.StringProperty(
        name="API Key Env",
        default="",
        description="Environment variable that contains the provider API key",
    )
    show_advanced: bpy.props.BoolProperty(
        name="Advanced",
        default=False,
        description="Show sidecar, model tuning, artifact, and bridge settings",
    )
    agent_python: bpy.props.StringProperty(
        name="Sidecar Python",
        default=_default_agent_python(),
        subtype="FILE_PATH",
        description="Python interpreter used to run the NodeCue SDK sidecar",
    )
    agent_sidecar_root: bpy.props.StringProperty(
        name="Sidecar Root",
        default=_default_sidecar_root(),
        subtype="DIR_PATH",
        description="Directory containing the nodecue_agent package",
    )
    agent_env_file: bpy.props.StringProperty(
        name="Env File",
        default=_default_env_file(),
        subtype="FILE_PATH",
        description="Optional .env file loaded by the sidecar for API keys/model settings",
    )
    agent_timeout_seconds: bpy.props.IntProperty(
        name="Timeout Seconds",
        default=240,
        min=30,
        max=1800,
    )
    agent_reasoning_effort: bpy.props.EnumProperty(
        name="Reasoning Effort",
        items=(
            ("none", "None", "Do not request provider-side reasoning tokens"),
            ("minimal", "Minimal", "Request minimal provider-side reasoning"),
            ("low", "Low", "Request low provider-side reasoning"),
            ("medium", "Medium", "Request medium provider-side reasoning"),
            ("high", "High", "Request high provider-side reasoning"),
        ),
        default="none",
    )
    agent_max_tokens: bpy.props.IntProperty(
        name="Max Tokens",
        default=4096,
        min=1024,
        max=32768,
    )
    agent_max_turns: bpy.props.IntProperty(
        name="Max Turns",
        default=35,
        min=5,
        max=80,
    )
    agent_artifact_root: bpy.props.StringProperty(
        name="Run Records Folder",
        default=_default_artifact_root(),
        subtype="DIR_PATH",
        description=(
            "Each run writes a report JSON and log here (plus an optional .blend copy). "
            "These records are what you attach when reporting a problem"
        ),
    )
    agent_save_blend_copy: bpy.props.BoolProperty(
        name="Save .blend Copy",
        default=True,
        description="Save a copy of the current Blender file after an agent run for manual review",
    )
    skill_path: bpy.props.StringProperty(
        name="Skill Path",
        default=DEFAULT_SKILL_PATH,
        subtype="DIR_PATH",
        description="Path to the Geometry Nodes skill package",
    )

    # --- Local Blender Bridge ---
    mcp_socket_port: bpy.props.IntProperty(
        name="Local Bridge Port", default=9877, min=1024, max=65535
    )

    # --- Asset Library Access ---
    asset_access_essentials: bpy.props.BoolProperty(
        name="Allow Access to Blender Built-in Assets",
        description="Let AI read Blender's bundled node group assets (Scatter on Surface, Array, etc.)",
        default=True,
    )
    asset_access_user: bpy.props.BoolProperty(
        name="Allow Access to User Asset Libraries",
        description="Let AI read node groups from your configured asset libraries (read-only)",
        default=False,
    )

    def draw(self, context):
        layout = self.layout

        # Basic: provider, model, key, dependencies. Everything else is Advanced.
        layout.prop(self, "agent_provider")
        if self.agent_provider == "openrouter":
            layout.prop(self, "agent_model_preset")
        layout.prop(self, "agent_model")
        if self.agent_provider in {"openai-compatible", "anthropic-compatible"}:
            layout.prop(self, "agent_base_url")
        layout.prop(self, "agent_api_key")

        dep_dir = _deps_dir()
        if agent_deps.deps_installed(dep_dir):
            layout.label(text="Sidecar dependencies installed", icon="CHECKMARK")
        else:
            row = layout.row(align=True)
            row.operator("gn_ai.install_agent_deps", icon="IMPORT")
            layout.label(
                text="Dependencies not installed yet - press Install Agent Dependencies",
                icon="ERROR",
            )

        # Asset Library Access: consent switches stay visible.
        layout.separator()
        layout.label(text="Asset Library Access")
        layout.prop(self, "asset_access_essentials", text="Let AI reuse Blender built-in node group assets")
        layout.prop(self, "asset_access_user", text="Let AI reuse node groups from my asset libraries")
        if self.asset_access_essentials or self.asset_access_user:
            row = layout.row()
            row.operator("gn_ai.scan_asset_libraries", text="Scan Libraries", icon="ASSET_MANAGER")

        # Advanced: collapsed by default.
        layout.separator()
        layout.prop(self, "show_advanced", toggle=True, icon="PREFERENCES")
        if self.show_advanced:
            box = layout.box()
            box.label(text="Model Tuning")
            box.prop(self, "agent_reasoning_effort")
            box.prop(self, "agent_timeout_seconds")
            box.prop(self, "agent_max_tokens")
            box.prop(self, "agent_max_turns")

            box.separator()
            box.label(text="Sidecar Python (change only if dependencies fail on Blender's own Python)")
            box.prop(self, "agent_python")
            row = box.row(align=True)
            row.operator("gn_ai.install_agent_deps", icon="IMPORT")

            box.separator()
            box.label(text="Run Records (report JSON + logs per run; attach these to bug reports)")
            box.prop(self, "agent_artifact_root")
            box.prop(self, "agent_save_blend_copy")

            box.separator()
            box.label(text="Local Bridge (managed automatically)")
            box.prop(self, "mcp_socket_port")


class GN_AI_Properties(bpy.types.PropertyGroup):
    status: bpy.props.StringProperty(
        name="Status",
        default="",
    )
    prompt: bpy.props.StringProperty(
        name="Prompt",
        default="",
        description="Describe the node graph to generate, modify, or explain",
    )
    mode: bpy.props.EnumProperty(
        name="Mode",
        items=(
            ("generate", "Generate", "Create a new teachable node graph"),
            ("explain", "Explain", "Explain the active node group"),
            ("modify", "Modify", "Modify or complete the active node group"),
        ),
        default="generate",
    )
    agent_output: bpy.props.StringProperty(
        name="Agent Output",
        default="",
    )
    agent_report_path: bpy.props.StringProperty(
        name="Agent Report",
        default="",
    )
    agent_blend_path: bpy.props.StringProperty(
        name="Agent Blend",
        default="",
    )


class GN_AI_OT_StartSocketServer(bpy.types.Operator):
    bl_idname = "gn_ai.start_socket_server"
    bl_label = "Start NodeCue Bridge"
    bl_description = "Start the NodeCue bridge server"

    def execute(self, context):
        from nodecue.socket_server import start_server

        prefs = context.preferences.addons[__package__].preferences
        start_server(port=prefs.mcp_socket_port)
        self.report({"INFO"}, f"NodeCue bridge started on port {prefs.mcp_socket_port}")
        return {"FINISHED"}


class GN_AI_OT_StopSocketServer(bpy.types.Operator):
    bl_idname = "gn_ai.stop_socket_server"
    bl_label = "Stop NodeCue Bridge"
    bl_description = "Stop the NodeCue bridge server"

    def execute(self, context):
        from nodecue.socket_server import stop_server

        stop_server()
        self.report({"INFO"}, "NodeCue bridge stopped")
        return {"FINISHED"}


class GN_AI_OT_ScanAssetLibraries(bpy.types.Operator):
    bl_idname = "gn_ai.scan_asset_libraries"
    bl_label = "Scan Asset Libraries"
    bl_description = "Scan enabled asset libraries and report available node groups"

    def execute(self, context):
        import os

        prefs = context.preferences.addons[__package__].preferences
        count = 0

        if prefs.asset_access_essentials:
            local_res = bpy.utils.resource_path("LOCAL")
            essentials_dir = os.path.join(local_res, "datafiles", "assets", "nodes")
            if os.path.isdir(essentials_dir):
                for fname in os.listdir(essentials_dir):
                    if fname.endswith(".blend"):
                        try:
                            with bpy.data.libraries.load(
                                os.path.join(essentials_dir, fname), assets_only=True
                            ) as (src, _dst):
                                count += len(src.node_groups)
                        except Exception:
                            pass

        if prefs.asset_access_user:
            for lib in context.preferences.filepaths.asset_libraries:
                if not os.path.isdir(lib.path):
                    continue
                for root, _dirs, files in os.walk(lib.path):
                    for fname in files:
                        if not fname.endswith(".blend"):
                            continue
                        try:
                            with bpy.data.libraries.load(
                                os.path.join(root, fname), assets_only=True
                            ) as (src, _dst):
                                count += len(src.node_groups)
                        except Exception:
                            pass

        self.report({"INFO"}, f"Found {count} node group assets")
        return {"FINISHED"}


def _summarize_agent_report(report: dict) -> str:
    lines = [
        f"stage: {report.get('stage', '')}",
        f"provider: {report.get('provider', {}).get('kind', '')} / {report.get('provider', {}).get('model', '')}",
    ]
    error = str(report.get("error") or "").strip()
    if error:
        lines.append(f"error: {error[:500]}")
    sdk_result = report.get("sdk_result") if isinstance(report.get("sdk_result"), dict) else {}
    actions = sdk_result.get("action_results") if isinstance(sdk_result, dict) else []
    if isinstance(actions, list):
        raw_actions = [
            action for action in actions
            if isinstance(action, dict) and isinstance(action.get("action"), dict)
        ]
        lines.append(f"raw blender actions: {len(raw_actions)}")
        guidance_count = len(actions) - len(raw_actions)
        if guidance_count:
            lines.append(f"blender tool guidance: {guidance_count}")
    stages = sdk_result.get("stage_results") if isinstance(sdk_result, dict) else []
    if isinstance(stages, list):
        lines.append(f"execution stages: {len(stages)}")
    skill_files = sdk_result.get("skill_files_read") if isinstance(sdk_result, dict) else []
    if isinstance(skill_files, list):
        lines.append(f"skill files read: {len(skill_files)}")
    readback = sdk_result.get("readback") if isinstance(sdk_result, dict) else None
    if isinstance(readback, dict):
        nodes = readback.get("nodes")
        links = readback.get("links")
        frames = readback.get("frames")
        if isinstance(nodes, list):
            lines.append(f"nodes: {len(nodes)}")
            names = [
                f"{node.get('name')} ({node.get('bl_idname')})"
                for node in nodes
                if isinstance(node, dict)
            ]
            lines.extend(names[:8])
        if isinstance(links, list):
            lines.append(f"links: {len(links)}")
        if isinstance(frames, list):
            lines.append(f"frames: {len(frames)}")
    final_output = str(report.get("final_output") or "").strip()
    if final_output:
        lines.append("final:")
        lines.extend(final_output.splitlines()[:14])
    blend_path = str(report.get("blend_path") or "").strip()
    if blend_path:
        lines.append(f"blend: {blend_path}")
    return "\n".join(lines)


def _agent_setup_report(prefs) -> tuple[bool, str]:
    errors = _validate_agent_configuration(prefs)
    file_values = _load_env_values(prefs.agent_env_file.strip())
    env_values = dict(os.environ)
    env_values.update({key: value for key, value in file_values.items() if key not in env_values})
    model = prefs.agent_model.strip() or env_values.get("NODECUE_AGENT_MODEL", "").strip()
    api_key_env = _resolved_api_key_env(
        prefs.agent_provider,
        prefs.agent_api_key_env.strip() or env_values.get("NODECUE_AGENT_API_KEY_ENV", "").strip(),
    )
    api_key, api_key_source = resolved_api_key(
        dict(os.environ),
        file_values,
        api_key_env=api_key_env,
        prefs_api_key=prefs.agent_api_key,
    )
    if not _provider_requires_api_key(prefs.agent_provider) and not api_key:
        key_line = "api key: (not required)"
    elif api_key:
        key_line = f"api key: set (from {api_key_source})"
    else:
        key_line = "api key: missing"
    lines = [
        "NodeCue setup check",
        f"provider: {prefs.agent_provider}",
        f"model: {model or '(missing)'}",
        key_line,
        f"deps: {'installed' if agent_deps.deps_installed(_deps_dir()) else 'not installed'}",
        f"skill path: {prefs.skill_path}",
    ]
    if errors:
        lines.append("errors:")
        lines.extend(errors)
    else:
        lines.append("status: OK")
    return not errors, "\n".join(lines)


def _validate_agent_configuration(prefs) -> list[str]:
    errors: list[str] = []
    python_path = Path((prefs.agent_python or _default_agent_python()).strip()).expanduser()
    sidecar_root = Path((prefs.agent_sidecar_root or _default_sidecar_root()).strip()).expanduser()
    skill_path = Path((prefs.skill_path or DEFAULT_SKILL_PATH).strip()).expanduser()
    file_values = _load_env_values(prefs.agent_env_file.strip())
    env_values = dict(os.environ)
    env_values.update({key: value for key, value in file_values.items() if key not in env_values})

    if prefs.agent_provider not in {
        "openrouter",
        "openai",
        "openai-compatible",
        "anthropic",
        "anthropic-compatible",
    }:
        errors.append(
            f"Provider '{prefs.agent_provider}' is not supported by the SDK-backed plugin runner yet."
        )
    if not python_path.exists():
        errors.append(f"Sidecar Python not found: {python_path}")
    if not sidecar_root.exists():
        errors.append(f"Sidecar root not found: {sidecar_root}")
    elif not (sidecar_root / "nodecue_agent").exists():
        errors.append(f"nodecue_agent package not found under: {sidecar_root}")
    if not (skill_path / "SKILL.md").exists():
        errors.append(f"Geometry Nodes skill not found: {skill_path}")

    model = prefs.agent_model.strip() or env_values.get("NODECUE_AGENT_MODEL", "").strip()
    if not model:
        errors.append("Missing model. Set Model in the addon preferences.")

    api_key_env = _resolved_api_key_env(
        prefs.agent_provider,
        prefs.agent_api_key_env.strip() or env_values.get("NODECUE_AGENT_API_KEY_ENV", "").strip(),
    )
    api_key, _ = resolved_api_key(
        dict(os.environ),
        file_values,
        api_key_env=api_key_env,
        prefs_api_key=prefs.agent_api_key,
    )
    if _provider_requires_api_key(prefs.agent_provider) and not api_key:
        errors.append(
            f"Missing API key. Paste it into the API Key field, or provide {api_key_env} "
            "via the environment or an Env File."
        )

    if not errors:
        env = compose_sidecar_env(
            dict(os.environ),
            file_values,
            api_key_env=api_key_env,
            prefs_api_key=prefs.agent_api_key,
        )
        env["PYTHONPATH"] = _sidecar_pythonpath(sidecar_root) + os.pathsep + env.get("PYTHONPATH", "")
        try:
            proc = subprocess.run(
                [
                    str(python_path),
                    "-c",
                    "import agents, openai, nodecue_agent",
                ],
                cwd=str(sidecar_root),
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            if proc.returncode != 0:
                errors.append(
                    "Sidecar Python cannot import agents/openai/nodecue_agent: "
                    + (proc.stderr or proc.stdout)[-500:]
                )
                errors.append(
                    "Press 'Install Agent Dependencies' in the NodeCue panel or "
                    "add-on preferences, then run Check Setup again."
                )
        except Exception as exc:
            errors.append(f"Sidecar dependency check failed: {exc}")
    return errors


def _save_agent_blend_copy(report: dict) -> tuple[str, str]:
    global _AGENT_ARTIFACT_DIR

    artifact_dir = _AGENT_ARTIFACT_DIR
    if artifact_dir is None and _AGENT_REPORT_PATH:
        artifact_dir = _AGENT_REPORT_PATH.parent
    if artifact_dir is None:
        artifact_dir = Path(tempfile.gettempdir()) / "nodecue_plugin_agent"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    mode = str(report.get("mode") or "nodecue")
    blend_path = artifact_dir / f"{_sanitize_artifact_part(mode)}_result.blend"
    try:
        bpy.ops.wm.save_as_mainfile(
            filepath=str(blend_path),
            check_existing=False,
            copy=True,
        )
    except Exception as exc:
        return "", str(exc)
    return str(blend_path), ""


def _poll_agent_process() -> float | None:
    global _AGENT_PROCESS, _AGENT_REPORT_PATH, _AGENT_STDERR_PATH, _AGENT_CANCEL_REQUESTED

    if _AGENT_PROCESS is None:
        return None
    if _AGENT_PROCESS.poll() is None:
        try:
            props = bpy.context.scene.gn_ai_props
            props.status = "NodeCue agent canceling..." if _AGENT_CANCEL_REQUESTED else "NodeCue agent running..."
        except Exception:
            pass
        return 1.0

    returncode = _AGENT_PROCESS.returncode
    report = None
    if _AGENT_REPORT_PATH and _AGENT_REPORT_PATH.exists():
        try:
            report = json.loads(_AGENT_REPORT_PATH.read_text(encoding="utf-8"))
        except Exception:
            report = None

    stderr_text = ""
    if _AGENT_STDERR_PATH and _AGENT_STDERR_PATH.exists():
        try:
            stderr_text = _AGENT_STDERR_PATH.read_text(encoding="utf-8")[-2000:]
        except Exception:
            stderr_text = ""

    try:
        props = bpy.context.scene.gn_ai_props
        prefs = bpy.context.preferences.addons[__package__].preferences
        if report:
            if returncode == 0 and prefs.agent_save_blend_copy:
                blend_path, save_error = _save_agent_blend_copy(report)
                if blend_path:
                    report["blend_path"] = blend_path
                    props.agent_blend_path = blend_path
                if save_error:
                    report["blend_save_error"] = save_error
                if _AGENT_REPORT_PATH:
                    _AGENT_REPORT_PATH.write_text(
                        json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            props.agent_output = _summarize_agent_report(report)
            if _AGENT_CANCEL_REQUESTED:
                props.status = "NodeCue agent canceled"
            else:
                props.status = "NodeCue agent finished" if returncode == 0 else "NodeCue agent finished with issues"
        else:
            props.agent_output = stderr_text or f"Sidecar exited with code {returncode}"
            props.status = "NodeCue agent canceled" if _AGENT_CANCEL_REQUESTED else "NodeCue agent failed"
        if _AGENT_REPORT_PATH:
            props.agent_report_path = str(_AGENT_REPORT_PATH)
    except Exception:
        pass

    _AGENT_PROCESS = None
    _AGENT_CANCEL_REQUESTED = False
    return None


def _poll_deps_process() -> float | None:
    global _DEPS_PROCESS, _DEPS_LOG_PATH

    if _DEPS_PROCESS is None:
        return None
    if _DEPS_PROCESS.poll() is None:
        try:
            bpy.context.scene.gn_ai_props.status = "Installing sidecar dependencies..."
        except Exception:
            pass
        return 1.0

    returncode = _DEPS_PROCESS.returncode
    log_tail = ""
    if _DEPS_LOG_PATH and _DEPS_LOG_PATH.exists():
        try:
            log_tail = _DEPS_LOG_PATH.read_text(encoding="utf-8")[-2000:]
        except Exception:
            log_tail = ""

    try:
        props = bpy.context.scene.gn_ai_props
        if returncode == 0:
            props.status = "Sidecar dependencies installed"
            props.agent_output = "Dependency install finished. Run Check Setup to verify."
        else:
            props.status = "Sidecar dependency install failed"
            props.agent_output = log_tail or f"pip exited with code {returncode}"
    except Exception:
        pass

    _DEPS_PROCESS = None
    return None


class GN_AI_OT_InstallAgentDeps(bpy.types.Operator):
    bl_idname = "gn_ai.install_agent_deps"
    bl_label = "Install Agent Dependencies"
    bl_description = (
        "Download the sidecar's Python packages into a NodeCue-managed directory "
        "using the sidecar Python (no manual virtualenv needed; requires network)"
    )

    def execute(self, context):
        global _DEPS_PROCESS, _DEPS_LOG_PATH

        props = context.scene.gn_ai_props
        prefs = context.preferences.addons[__package__].preferences
        if _DEPS_PROCESS is not None and _DEPS_PROCESS.poll() is None:
            self.report({"WARNING"}, "Dependency install is already running")
            return {"CANCELLED"}
        if _AGENT_PROCESS is not None and _AGENT_PROCESS.poll() is None:
            self.report({"WARNING"}, "Stop the running NodeCue agent first")
            return {"CANCELLED"}

        requirements = agent_deps.requirements_path()
        if not requirements.exists():
            msg = f"Bundled requirements file missing: {requirements}"
            props.status = msg
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}

        python_path = (prefs.agent_python or _default_agent_python()).strip()
        target = _deps_dir()
        target.mkdir(parents=True, exist_ok=True)
        _DEPS_LOG_PATH = target / "install.log"
        cmd = agent_deps.pip_install_command(python_path, target, requirements)

        log_file = _DEPS_LOG_PATH.open("w", encoding="utf-8")
        try:
            _DEPS_PROCESS = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except Exception as exc:
            log_file.close()
            msg = f"Failed to start dependency install: {exc}"
            props.status = msg
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        log_file.close()

        props.status = "Installing sidecar dependencies..."
        props.agent_output = f"Installing into {target}\nLog: {_DEPS_LOG_PATH}"
        if not bpy.app.timers.is_registered(_poll_deps_process):
            bpy.app.timers.register(_poll_deps_process, first_interval=1.0, persistent=False)
        self.report({"INFO"}, "Dependency install started")
        return {"FINISHED"}


class GN_AI_OT_RunAgentPrototype(bpy.types.Operator):
    bl_idname = "gn_ai.run_agent_prototype"
    bl_label = "Run NodeCue Agent"
    bl_description = "Run the NodeCue SDK sidecar against the active Blender session"

    def execute(self, context):
        global _AGENT_PROCESS, _AGENT_REPORT_PATH, _AGENT_STDERR_PATH, _AGENT_ARTIFACT_DIR, _AGENT_CANCEL_REQUESTED

        props = context.scene.gn_ai_props
        prefs = context.preferences.addons[__package__].preferences
        if _AGENT_PROCESS is not None and _AGENT_PROCESS.poll() is None:
            msg = "NodeCue agent is already running"
            props.status = msg
            self.report({"WARNING"}, msg)
            return {"CANCELLED"}
        if not props.prompt.strip():
            msg = "Prompt is empty"
            props.status = msg
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}

        errors = _validate_agent_configuration(prefs)
        if errors:
            props.status = "NodeCue agent configuration failed"
            props.agent_output = "\n".join(errors)
            self.report({"ERROR"}, errors[0])
            return {"CANCELLED"}

        from nodecue.socket_server import get_server, start_server

        srv = get_server()
        if srv is None or not srv.is_running:
            start_server(port=prefs.mcp_socket_port)

        env_values = _load_env_values(prefs.agent_env_file.strip())
        model = prefs.agent_model.strip() or env_values.get("NODECUE_AGENT_MODEL", "").strip()
        artifact_root = Path((prefs.agent_artifact_root or _default_artifact_root()).strip()).expanduser()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        artifact_dir = artifact_root / f"{stamp}_{props.mode}_{_sanitize_artifact_part(model)}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        _AGENT_ARTIFACT_DIR = artifact_dir
        _AGENT_REPORT_PATH = artifact_dir / "report.json"
        _AGENT_STDERR_PATH = artifact_dir / "stderr.log"
        _AGENT_CANCEL_REQUESTED = False
        if _AGENT_REPORT_PATH.exists():
            _AGENT_REPORT_PATH.unlink()
        if _AGENT_STDERR_PATH.exists():
            _AGENT_STDERR_PATH.unlink()

        api_key_env = prefs.agent_api_key_env.strip()
        if prefs.agent_provider == "openrouter" and api_key_env == "OPENAI_API_KEY":
            api_key_env = ""

        cmd = [
            prefs.agent_python or _default_agent_python(),
            "-m",
            "nodecue_agent.sdk_sidecar",
            "--prompt",
            props.prompt,
            "--mode",
            props.mode,
            "--skill-path",
            prefs.skill_path,
            "--host",
            "127.0.0.1",
            "--port",
            str(prefs.mcp_socket_port),
            "--provider",
            prefs.agent_provider,
            "--model",
            prefs.agent_model,
            "--base-url",
            prefs.agent_base_url,
            "--api-key-env",
            api_key_env,
            "--timeout-seconds",
            str(prefs.agent_timeout_seconds),
            "--max-turns",
            str(prefs.agent_max_turns),
            "--reasoning-effort",
            prefs.agent_reasoning_effort,
            "--max-tokens",
            str(prefs.agent_max_tokens),
            "--output",
            str(_AGENT_REPORT_PATH),
        ]
        if prefs.agent_env_file:
            cmd.extend(["--env-file", prefs.agent_env_file])

        resolved_key_env = _resolved_api_key_env(
            prefs.agent_provider,
            api_key_env or env_values.get("NODECUE_AGENT_API_KEY_ENV", "").strip(),
        )
        env = compose_sidecar_env(
            dict(os.environ),
            env_values,
            api_key_env=resolved_key_env,
            prefs_api_key=prefs.agent_api_key,
        )
        sidecar_root = prefs.agent_sidecar_root.strip() or _default_sidecar_root()
        env["NODECUE_AGENT_PROVIDER"] = prefs.agent_provider
        env["NODECUE_AGENT_REASONING_EFFORT"] = prefs.agent_reasoning_effort
        env["NODECUE_AGENT_MAX_TOKENS"] = str(prefs.agent_max_tokens)
        env["NODECUE_AGENT_TIMEOUT_SECONDS"] = str(prefs.agent_timeout_seconds)
        if prefs.agent_model.strip():
            env["NODECUE_AGENT_MODEL"] = prefs.agent_model.strip()
        if prefs.agent_base_url.strip():
            env["NODECUE_AGENT_BASE_URL"] = prefs.agent_base_url.strip()
        if api_key_env:
            env["NODECUE_AGENT_API_KEY_ENV"] = api_key_env
        env["PYTHONPATH"] = _sidecar_pythonpath(sidecar_root) + os.pathsep + env.get("PYTHONPATH", "")

        stderr_file = _AGENT_STDERR_PATH.open("w", encoding="utf-8")
        try:
            _AGENT_PROCESS = subprocess.Popen(
                cmd,
                cwd=sidecar_root,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                text=True,
            )
        except Exception as exc:
            stderr_file.close()
            msg = f"Failed to start NodeCue sidecar: {exc}"
            props.status = msg
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        stderr_file.close()

        props.status = "NodeCue agent running..."
        props.agent_output = ""
        props.agent_report_path = str(_AGENT_REPORT_PATH)
        props.agent_blend_path = ""

        if not bpy.app.timers.is_registered(_poll_agent_process):
            bpy.app.timers.register(_poll_agent_process, first_interval=1.0, persistent=False)
        self.report({"INFO"}, "NodeCue agent started")
        return {"FINISHED"}


class GN_AI_OT_CheckAgentSetup(bpy.types.Operator):
    bl_idname = "gn_ai.check_agent_setup"
    bl_label = "Check Setup"
    bl_description = "Check NodeCue SDK sidecar, provider, model, key, skill, and bridge setup"

    def execute(self, context):
        props = context.scene.gn_ai_props
        prefs = context.preferences.addons[__package__].preferences
        ok, message = _agent_setup_report(prefs)
        props.agent_output = message
        props.status = "NodeCue setup OK" if ok else "NodeCue setup has issues"
        self.report({"INFO"} if ok else {"ERROR"}, props.status)
        return {"FINISHED" if ok else "CANCELLED"}


class GN_AI_OT_CancelAgentRun(bpy.types.Operator):
    bl_idname = "gn_ai.cancel_agent_run"
    bl_label = "Cancel NodeCue Agent"
    bl_description = "Terminate the running NodeCue SDK sidecar"

    def execute(self, context):
        global _AGENT_PROCESS, _AGENT_CANCEL_REQUESTED

        props = context.scene.gn_ai_props
        if _AGENT_PROCESS is None or _AGENT_PROCESS.poll() is not None:
            props.status = "No NodeCue agent run is active"
            self.report({"WARNING"}, props.status)
            return {"CANCELLED"}
        _AGENT_CANCEL_REQUESTED = True
        _AGENT_PROCESS.terminate()
        props.status = "NodeCue agent canceling..."
        self.report({"INFO"}, "NodeCue agent canceling")
        return {"FINISHED"}


def _active_gn_node_group(context):
    obj = getattr(context, "active_object", None)
    if obj is None:
        return None
    for mod in getattr(obj, "modifiers", []):
        if getattr(mod, "type", "") == "NODES" and getattr(mod, "node_group", None) is not None:
            return mod.node_group
    return None


class GN_AI_OT_MarkResultAsset(bpy.types.Operator):
    bl_idname = "gn_ai.mark_result_asset"
    bl_label = "Mark Result as Asset"
    bl_description = (
        "Mark the active object's Geometry Nodes group as an asset so it can be "
        "saved into your asset library and reused by NodeCue in later prompts"
    )

    def execute(self, context):
        node_group = _active_gn_node_group(context)
        if node_group is None:
            self.report({"ERROR"}, "Active object has no Geometry Nodes modifier with a node group")
            return {"CANCELLED"}
        try:
            node_group.asset_mark()
            try:
                node_group.asset_generate_preview()
            except Exception:
                pass
        except Exception as exc:
            self.report({"ERROR"}, f"Could not mark asset: {exc}")
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"Marked '{node_group.name}' as an asset. Save this file into an asset "
            "library folder to reuse it in later prompts.",
        )
        return {"FINISHED"}


class GN_AI_PT_MainPanel(bpy.types.Panel):
    bl_label = "NodeCue"
    bl_idname = "GN_AI_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "NodeCue"

    def draw(self, context):
        layout = self.layout
        props = context.scene.gn_ai_props

        layout.prop(props, "mode")
        layout.prop(props, "prompt")
        if not agent_deps.deps_installed(_deps_dir()):
            layout.operator("gn_ai.install_agent_deps", icon="IMPORT")
        row = layout.row(align=True)
        row.operator("gn_ai.check_agent_setup", icon="CHECKMARK")
        row = layout.row(align=True)
        row.operator("gn_ai.run_agent_prototype", icon="PLAY")
        row.operator("gn_ai.cancel_agent_run", icon="CANCEL")

        if props.agent_output:
            box = layout.box()
            box.label(text="Agent Output")
            for line in props.agent_output.splitlines()[:24]:
                box.label(text=line[:120])
        if props.agent_report_path:
            layout.label(text=f"Report: {props.agent_report_path}", icon="FILE_TEXT")
        if props.agent_blend_path:
            layout.label(text=f"Blend: {props.agent_blend_path}", icon="FILE_BLEND")
        if _active_gn_node_group(context) is not None:
            layout.operator("gn_ai.mark_result_asset", icon="ASSET_MANAGER")
        if props.status:
            layout.label(text=props.status, icon="INFO")


CLASSES = (
    GN_AI_Properties,
    GN_AI_AddonPreferences,
    GN_AI_OT_StartSocketServer,
    GN_AI_OT_StopSocketServer,
    GN_AI_OT_ScanAssetLibraries,
    GN_AI_OT_InstallAgentDeps,
    GN_AI_OT_RunAgentPrototype,
    GN_AI_OT_CheckAgentSetup,
    GN_AI_OT_CancelAgentRun,
    GN_AI_OT_MarkResultAsset,
    GN_AI_PT_MainPanel,
)


def register_ui():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.gn_ai_props = bpy.props.PointerProperty(type=GN_AI_Properties)


def unregister_ui():
    if hasattr(bpy.types.Scene, "gn_ai_props"):
        del bpy.types.Scene.gn_ai_props
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
