# Troubleshooting

Use this when Check Setup fails, the sidecar does not start, or the model run exits before creating a node graph.

## Check Setup Cannot Import Dependencies

Symptom:

```text
Sidecar Python cannot import agents/openai/nodecue_agent
```

Fix:

1. Confirm the Python shown in `Sidecar Python` is the same environment where dependencies were installed.
2. From the unzipped NodeCue folder or repository root, run:

```bash
<sidecar-python> -m pip install -r requirements-agent.txt
```

3. Run Check Setup again.

## Sidecar Root Is Wrong

Symptom:

```text
nodecue_agent package not found
```

Fix:

- `Sidecar Root` should point to the installed add-ons directory that contains `nodecue_agent/`, not to `nodecue/` itself.
- On macOS Blender 5.1 this is usually:

```text
~/Library/Application Support/Blender/5.1/scripts/addons
```

## Env File Is Missing

Symptom:

```text
Missing API key
```

Fix:

1. Copy `nodecue.env.example` to `.env` in the same add-ons directory:

```bash
cp nodecue.env.example .env
```

2. Add your provider key:

```bash
OPENROUTER_API_KEY=...
NODECUE_AGENT_PROVIDER=openrouter
NODECUE_AGENT_MODEL=moonshotai/kimi-k2.6
```

3. Confirm `Env File` in Blender points to that `.env`.

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
- mode: Generate, Explain, or Modify;
- provider/model;
- report JSON snippet;
- screenshot of the node tree;
- shareable `.blend` file if possible;
- what looked wrong: missing output connection, disconnected nodes, wrong parameter, unclear explanation, or model timeout.

Do not share private asset-library paths or unreleasable `.blend` files in public issues.
