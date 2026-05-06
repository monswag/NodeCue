# NodeCue Quickstart

## Requirements

- Blender 5.1
- Python environment that can run the NodeCue sidecar
- OpenRouter API key or another OpenAI-compatible endpoint

## Configure

Copy `.env.example` to `.env` and fill in the model provider settings:

```bash
OPENROUTER_API_KEY=...
NODECUE_AGENT_PROVIDER=openrouter
NODECUE_AGENT_MODEL=moonshotai/kimi-k2.6
NODECUE_AGENT_REASONING_EFFORT=none
NODECUE_AGENT_MAX_TOKENS=4096
```

## Install for local testing

Copy `nodecue/` and `nodecue_agent/` into Blender's add-ons directory, or keep this repository on disk and point Blender's Python path to it during development.

For Blender 5.1 on macOS, the add-ons directory is usually:

```bash
~/Library/Application Support/Blender/5.1/scripts/addons/
```

## Use

1. Enable the `nodecue` add-on.
2. Open the NodeCue panel.
3. Run Check Setup.
4. Choose Generate, Explain, or Modify.
5. Enter a Geometry Nodes prompt and run the agent.

Generated reports and saved `.blend` artifacts are local debugging aids. Do not commit them to Git.
