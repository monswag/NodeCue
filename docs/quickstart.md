# NodeCue Quickstart

## Requirements

- Blender 5.0+ (most tested on 5.1)
- Network access once, to download sidecar packages
- OpenRouter API key or another OpenAI-compatible endpoint

## 1. Install the Blender Add-on

Download the release zip from GitHub Releases. The file name should look like:

```text
nodecue-v0.1.0-alpha.14-blender-addon.zip
```

Install it through Blender:

1. Open Blender 5.0 or newer.
2. Open `Edit > Preferences > Add-ons`.
3. Press `Install...`.
4. Select the NodeCue release zip.
5. Enable `NodeCue`.

The zip installs a normal Blender add-on package:

```text
nodecue/
  __init__.py
  nodecue_agent/
  skills/
  requirements-agent.txt
  nodecue.env.example
```

On macOS Blender 5.1, the installed add-on folder is usually:

```text
~/Library/Application Support/Blender/5.1/scripts/addons/nodecue/
```

## 2. Install Agent Dependencies (One Click)

NodeCue runs model calls in a separate Python sidecar. Its packages install from inside Blender — no terminal or virtualenv needed:

1. Open the NodeCue panel in the 3D View sidebar (or NodeCue Add-on Preferences).
2. Press `Install Agent Dependencies`.
3. Wait until the status shows `Sidecar dependencies installed`. This downloads packages from PyPI once.

The packages go into a NodeCue-managed folder (`nodecue-deps` under Blender's user scripts directory), installed with Blender's own Python. Nothing outside that folder is touched.

Advanced fallback: if your machine blocks the download or you prefer your own Python environment, create one manually and point `Sidecar Python` in preferences at it:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r "/path/to/Blender/5.1/scripts/addons/nodecue/requirements-agent.txt"
```

On Windows, the Python path is usually:

```text
.venv\Scripts\python.exe
```

## 3. Configure Model Access

In NodeCue Add-on Preferences:

1. Pick a `Provider` (OpenRouter by default).
2. Set `Model`, for example `moonshotai/kimi-k2.6`.
3. Paste your provider key into `API Key`.

The key is stored in Blender's preferences file in plain text and is passed to the sidecar only through environment variables. If you prefer file-based secrets, open `Advanced` and point `Env File` at a `nodecue.env` file instead (sample at `nodecue/nodecue.env.example`). When a key is available from several places, the priority is: OS environment, then the `API Key` field, then the `Env File`.

## 4. Run Check Setup

1. Open the NodeCue panel in the 3D View sidebar.
2. Run Check Setup and confirm it reports `status: OK`.

Sidecar Python/root, model tuning, artifact paths, and the local bridge port live under `Advanced` in the preferences and rarely need changes.

## 5. Try a Prompt

Choose Generate and try:

```text
Create a teachable Geometry Nodes setup that displaces a grid terrain with noise, exposes height and scale controls, and frames the graph so a beginner can understand it.
```

The run should produce:

- a Geometry Nodes graph in the current Blender file;
- a report JSON path shown in the panel;
- an optional saved `.blend` copy for manual review.

Generated reports and saved `.blend` artifacts are local debugging aids. Do not commit them to Git.

## Troubleshooting

- If Check Setup cannot import `agents` or `openai`, press `Install Agent Dependencies` and wait for it to finish, then run Check Setup again.
- If the model is missing, set `NODECUE_AGENT_MODEL` in `.env` or in Add-on Preferences.
- If the API key is missing, confirm `OPENROUTER_API_KEY` exists in the selected `.env`.
- If the bridge is stopped, press Start Bridge or run Check Setup again.

More detailed setup fixes are in [troubleshooting.md](troubleshooting.md).
