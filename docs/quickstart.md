# NodeCue Quickstart

## Requirements

- Blender 5.1
- Python 3.11+ environment that can run the NodeCue sidecar
- OpenRouter API key or another OpenAI-compatible endpoint

## 1. Install Python Dependencies

Create a small Python environment for the sidecar. You can use any Python environment that Blender can launch:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-agent.txt
```

On Windows, the Python path is usually:

```text
.venv\Scripts\python.exe
```

## 2. Install the Blender Add-on

From this repository root:

```bash
python3 scripts/install_addon.py --blender-version 5.1 --force
```

On Windows, use `py scripts\install_addon.py ...` if `python3` is not available.

The installer copies these files into Blender's add-ons directory:

```text
nodecue/
nodecue_agent/
requirements-agent.txt
nodecue.env.example
```

For Blender 5.1 on macOS, the add-ons directory is usually:

```bash
~/Library/Application Support/Blender/5.1/scripts/addons/
```

You can override the target:

```bash
python3 scripts/install_addon.py --addons-dir /path/to/Blender/5.1/scripts/addons --force
```

## 3. Configure Model Access

Copy the installed env example to `.env` in the same add-ons directory:

```bash
cp "$HOME/Library/Application Support/Blender/5.1/scripts/addons/nodecue.env.example" \
  "$HOME/Library/Application Support/Blender/5.1/scripts/addons/.env"
```

Fill in the provider settings:

```bash
OPENROUTER_API_KEY=...
NODECUE_AGENT_PROVIDER=openrouter
NODECUE_AGENT_MODEL=moonshotai/kimi-k2.6
NODECUE_AGENT_REASONING_EFFORT=none
NODECUE_AGENT_MAX_TOKENS=4096
```

## 4. Enable and Configure in Blender

1. Enable the `nodecue` add-on.
2. Open Add-on Preferences for NodeCue.
3. Set `Sidecar Python` to the Python environment from step 1.
4. Confirm `Sidecar Root` points to Blender's add-ons directory.
5. Confirm `Env File` points to the installed `.env`.
6. Open the NodeCue panel in the 3D View sidebar.
7. Run Check Setup.

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

- If Check Setup cannot import `agents` or `openai`, install `requirements-agent.txt` into the Python shown in `Sidecar Python`.
- If the model is missing, set `NODECUE_AGENT_MODEL` in `.env` or in Add-on Preferences.
- If the API key is missing, confirm `OPENROUTER_API_KEY` exists in the selected `.env`.
- If the bridge is stopped, press Start Bridge or run Check Setup again.
