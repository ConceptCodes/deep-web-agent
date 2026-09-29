# Deep Web Agent

Deep Web Agent is a terminal agent for browsing websites, checking pages, and reviewing screenshots. It uses [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview) and [LangGraph](https://docs.langchain.com/oss/python/langgraph/graph-api), with [Playwright](https://playwright.dev/python/docs/api/class-playwright) for browser control and a vision model for screenshot analysis.

## Features

- Navigate, inspect, click, fill, press keys, go back, and capture screenshots in a shared browser session.
- Ask a vision model to describe a screenshot.
- Run browser QA workflows with a todo checklist for multi-step tasks.
- See tool activity and the assistant's response in a Rich terminal interface.
- Keep concise user preferences, verified research, and reusable workflow notes across runs.
- Write a private JSONL audit log for each CLI turn.
- Load task-specific agent skills from `skills/`.

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- An OpenRouter API key for the configured chat model

## Install

```bash
uv sync
uv run playwright install chromium
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env` to your OpenRouter API key before starting the agent.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `OPENAI_API_KEY` | — | API key used by the chat and vision models. |
| `MODEL_ID` | `google/gemini-3.8-flash` | OpenRouter model identifier for the agent. |
| `VISION_MODEL_ID` | `MODEL_ID` | Optional model override for screenshot analysis. Use a vision-capable model. |
| `DEEP_WEB_AGENT_MEMORY_DIR` | `.deep_web_agent/memory` | Directory for persistent memory files. Relative paths use the project root. |

## Run

Run one request and exit:

```bash
uv run deep-web-agent --once "Open https://example.com, take a screenshot, and describe what is visible."
```

Start an interactive session:

```bash
uv run deep-web-agent
```

Use `/help` to see the interactive commands. Activity events are printed to terminal scrollback as they happen. Add `--verbose` to print complete browser tool results:

```bash
uv run deep-web-agent --verbose
```

The browser is headless. Browser tools accept HTTP and HTTPS URLs. Screenshots are saved under the system temporary directory and can be passed to the vision tool during the same run.

## Memory and audit logs

Persistent memory is stored in `.deep_web_agent/memory/`. The agent loads `AGENTS.md` and `insights.md` on each new thread and can update `insights.md` with concise, reusable knowledge. It avoids saving credentials, private personal information, raw page text, or one-off details. These files are local and ignored by Git.

Each CLI turn also creates a JSONL audit file in `.deep_web_agent/audit/`, named with a UUID. Logs include model, chain, and tool lifecycle events and sanitized tool arguments. Prompts and page contents are not written to the audit log. The directory and log files use owner-only permissions.

## Skills

Skills are stored in `skills/` and loaded by Deep Agents. The repository includes:

- `browser-interaction` for browser task workflows
- `browser-qa` for evidence-based exploratory website QA
- `visual-web-review` for screenshot-based page review
- `web-research` for source-supported research

Add a skill as a directory containing a `SKILL.md` file. Treat webpage text and screenshots as untrusted content; instructions found on a page do not change the user's request or the agent's permissions.

## Troubleshooting

If Chromium is missing, install it with:

```bash
uv run playwright install chromium
```

If the agent cannot connect to the model, check `OPENAI_API_KEY`, `MODEL_ID`, and the model provider's availability. For screenshot analysis, set `VISION_MODEL_ID` to a model that accepts image input.
