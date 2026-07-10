# NodeCue Quickstart

## Requirements

- Blender 5.0+ (most tested on 5.1)
- Python 3.11+ environment that can run the NodeCue sidecar
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

## 2. Install Sidecar Python Dependencies

NodeCue runs model calls in a separate Python sidecar. This is the one setup step that still needs a Python environment in the current alpha.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r "/path/to/Blender/5.1/scripts/addons/nodecue/requirements-agent.txt"
```

On Windows, the Python path is usually:

```text
.venv\Scripts\python.exe
```

## 3. Configure Model Access

Create a text file named `nodecue.env` anywhere convenient, then paste your provider settings into it:

```text
OPENROUTER_API_KEY=...
NODECUE_AGENT_PROVIDER=openrouter
NODECUE_AGENT_MODEL=moonshotai/kimi-k2.6
NODECUE_AGENT_REASONING_EFFORT=none
NODECUE_AGENT_MAX_TOKENS=4096
```

There is also a sample file at `nodecue/nodecue.env.example` inside the installed add-on folder.

## 4. Configure in Blender

1. Open Add-on Preferences for NodeCue.
2. Set `Sidecar Python` to the Python environment from step 2.
3. Confirm `Sidecar Root` points to the installed `nodecue` add-on folder.
4. Set `Env File` to your `nodecue.env` file.
5. Open the NodeCue panel in the 3D View sidebar.
6. Run Check Setup.

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

- If Check Setup cannot import `agents` or `openai`, install the included `requirements-agent.txt` into the Python shown in `Sidecar Python`.
- If the model is missing, set `NODECUE_AGENT_MODEL` in `.env` or in Add-on Preferences.
- If the API key is missing, confirm `OPENROUTER_API_KEY` exists in the selected `.env`.
- If the bridge is stopped, press Start Bridge or run Check Setup again.

More detailed setup fixes are in [troubleshooting.md](troubleshooting.md).
