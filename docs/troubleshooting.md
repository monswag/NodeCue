# Troubleshooting

Use this when Check Setup fails, the sidecar does not start, or the model run exits before creating a node graph.

## Check Setup Cannot Import Dependencies

Symptom:

```text
Sidecar Python cannot import agents/openai/nodecue_agent
```

Fix:

1. Press `Install Agent Dependencies` in the NodeCue panel or add-on preferences and wait for `Sidecar dependencies installed`. The install log is written to `install.log` inside the `nodecue-deps` folder.
2. Run Check Setup again.

Manual fallback (offline machines or custom Python environments): install the included `requirements-agent.txt` into the Python shown in `Sidecar Python`:

```bash
<sidecar-python> -m pip install -r "/path/to/Blender/5.1/scripts/addons/nodecue/requirements-agent.txt"
```

## Sidecar Root Is Wrong

Symptom:

```text
nodecue_agent package not found
```

Fix:

- `Sidecar Root` should point to the installed `nodecue` add-on folder that contains `nodecue_agent/`.
- On macOS Blender 5.1 this is usually:

```text
~/Library/Application Support/Blender/5.1/scripts/addons/nodecue
```

If you installed an earlier NodeCue build, Blender may keep the old saved preference. Manually set `Sidecar Root` to the installed `nodecue` folder after installing the new zip.

## API Key Is Missing

Symptom:

```text
Missing API key
```

Fix:

1. Paste your provider key into the `API Key` field in NodeCue Add-on Preferences.
2. Run Check Setup again; it should report `api key: set (from preferences)`.

File-based alternative: open `Advanced`, point `Env File` at a `nodecue.env` file containing `OPENROUTER_API_KEY=...`. When both exist, the OS environment wins over the `API Key` field, which wins over the `Env File`.

Do not paste API keys into GitHub issues.

## Model Or Provider Is Missing

Symptom:

```text
Missing model
```

Fix:

- Set `NODECUE_AGENT_MODEL` in `.env`, or set Model in Add-on Preferences.
- For OpenRouter, use a full OpenRouter model id, for example:

```text
moonshotai/kimi-k2.6
```

Model quality varies. If one model produces disconnected or confusing graphs, try a stronger model before reporting a graph-quality bug.

## Sidecar Starts But Nothing Happens

Try:

- run Check Setup again;
- confirm the bridge is started;
- open Blender's console or system terminal and look for sidecar errors;
- check the report JSON path shown in the NodeCue panel;
- reduce the prompt to one small Geometry Nodes task.

Useful first prompt:

```text
Create a teachable Geometry Nodes setup that displaces a grid terrain with noise, exposes height and scale controls, and frames the graph so a beginner can understand it.
```

## Generated Graph Looks Wrong

Useful report details:

- prompt;
- button used: Build or Explain;
- provider/model;
- report JSON snippet;
- screenshot of the node tree;
- shareable `.blend` file if possible;
- what looked wrong: missing output connection, disconnected nodes, wrong parameter, unclear explanation, or model timeout.

Do not share private asset-library paths or unreleasable `.blend` files in public issues.
