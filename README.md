# claude_token_report

Shows **where your Claude Code tokens actually go**: which activities (reading files, searching,
editing, git, subagents...), which models, projects and sessions. It also shows how much long
conversations and an expired cache add to your usage.

- reads only local transcripts (`~/.claude/projects/**/*.jsonl`)
- sends nothing and calls no API, so it uses **0 tokens**
- one file, Python 3.8+, no dependencies
- English by default, Polish with `-l pl`

## Install

```bash
git clone https://github.com/dgrebowiec/claude-token-report.git
cd claude-token-report
python3 claude_token_report.py --help
```

Optionally put it on your `PATH`: `ln -s "$PWD/claude_token_report.py" ~/.local/bin/claude-token-report`

## Usage

```bash
python3 claude_token_report.py                  # last 7 days in the terminal
python3 claude_token_report.py --explain        # what raw and weighted tokens mean
python3 claude_token_report.py --days 14 --daily         # last 14 days + each day's rise/fall
python3 claude_token_report.py --date 2026-09-15         # one specific day
python3 claude_token_report.py --from 09-01 --to 09-15   # a date range (inclusive)
python3 claude_token_report.py --today --diff   # today vs yesterday
python3 claude_token_report.py --days 30 --chart week
python3 claude_token_report.py -l pl            # Polish
python3 claude_token_report.py --list           # recent sessions
python3 claude_token_report.py --session 1a2b   # one session, usage per request
python3 claude_token_report.py --html report.html --private   # shareable HTML, no names or prompts
```

Dates: `YYYY-MM-DD`, `DD.MM.YYYY`, `MM-DD` (current year), `today`, `yesterday`.

`--daily` compares every day with the day before it: the change in weighted tokens (▲/▼), cache hit rate,
usage per call and the activity that changed the most. It works in the terminal and in the HTML report.
In the HTML report every metric has a `?` you can hover over or tap for an explanation.

## Two measures

This report is for Claude **subscriptions** (Pro/Max), so it shows no money, only tokens.

| measure | what it is |
|---|---|
| **raw tokens** | all text that went through the model, every token counted the same. The model re-reads the whole conversation on every call, so this is huge and mostly cheap cache reads. |
| **weighted tokens** | the main measure: each token counted by how heavily it uses your limit. Cache read x0.1, new input x1, cache write x1.25 (5 min) / x2 (1 h), output x5, times the model weight (Opus 5 x1, Opus 5.5 x0.8, Sonnet 5 x0.4, Haiku 4.5 x0.2, Fable 5.x x2). |

The weights are the price ratios from Anthropic's public API pricing. Anthropic does not publish the formula
behind subscription limits, so the report assumes limits count tokens in the same proportions. That is an
approximation, not an official number. Run `--explain` for the full explanation with a worked example.

The weights live in the `PRICES` table at the top of the script (as of 2026-09). Only the ratios matter.
You can override them with `--prices my.json`, for example `{"opus-5": [5, 25, 0.5]}` (input, output, cache read).

## License

[MIT](LICENSE)
