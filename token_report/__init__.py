"""Where do your Claude Code tokens actually go?

Reads ONLY the local Claude Code transcripts (~/.claude/projects/**/*.jsonl).
Sends nothing anywhere, calls no API, uses 0 tokens. Python 3.8+, no dependencies.

Modules, in the order data flows through them:
  transcripts  read the .jsonl files into Call and SessionMeta objects
  pricing      token types and weights (how much each token counts)
  classify     which activity (tool / kind of shell command) a call belongs to
  stats        aggregate calls into Stats; daily: the --daily comparison; tips: suggestions
  report_text / report_html   render the reports; cli: the command line
"""
