# test-case-generation

A skill that turns a **PRD** and a **TD** (Technical Design) from Confluence
into a QA test-case spreadsheet (`.xlsx`) with two sheets:

- **E2E Test Cases** – from the PRD, including UI and flow verification from any images
- **API Test Cases** – from the TD, with scenario-specific edge and negative cases

Where the PRD and an image (or the TD) disagree, the test case follows the PRD
and the mismatch is noted in the Remarks column.

## What's inside

```
test-case-generation/
├── SKILL.md                      # instructions Claude follows
├── config.example.json           # token template (do not put a real token here)
└── scripts/
    ├── fetch_confluence_page.py  # fetches a Confluence page + images
    └── generate_xlsx.py          # builds the spreadsheet
```

## Requirements

- Python 3 with `requests`, `beautifulsoup4`, `openpyxl`
  (the skill creates a venv at `/tmp/tcgen-venv` automatically if needed)
- Network access to `confluence.shopee.io` (skip if you use the no-token fallback)
- A Confluence Personal Access Token (skip if you use the no-token fallback)

## Install

### Claude Code (CLI / VS Code) — recommended

```bash
# for all your projects
cp -r test-case-generation ~/.claude/skills/

# or for one project only
cp -r test-case-generation <your-project>/.claude/skills/
```

Restart Claude Code. The skill triggers when you paste Confluence links or ask
for test cases, e.g. "buatkan test case dari confluence ini".

### Claude Desktop / claude.ai

1. **Remove `config.json` if you created one** — a token inside the zip will be
   rejected by the security check (and is unsafe anyway).
2. Zip the `test-case-generation` folder so that `SKILL.md` is inside it.
3. Go to **Settings → Capabilities → Skills → Upload skill** and select the zip.
4. Enable the skill.

Note: here the skill runs in a sandbox, so it cannot read files on your Mac and
may not reach internal Confluence. See "Authentication" below.

### Other agents

Anything that can read a `SKILL.md` and run Python can use it: point the agent
at `SKILL.md` as its instructions and make sure it can run the two scripts.

## Authentication

The fetch script looks for a token in this order:

1. Env var `CONFLUENCE_TOKEN` (optional `CONFLUENCE_BASE_URL`)
2. `~/.config/confluence/config.json`
3. `config.json` next to `SKILL.md` (gitignored; local installs only)

Create a token at: confluence.shopee.io → profile avatar → **Personal Access
Tokens** → **Create token** (use a short expiry).

User-level config (Claude Code / local use):

```bash
mkdir -p ~/.config/confluence
cat > ~/.config/confluence/config.json <<'EOF'
{ "base_url": "https://confluence.shopee.io", "token": "<your token>" }
EOF
chmod 600 ~/.config/confluence/config.json
```

Or just `export CONFLUENCE_TOKEN=<your token>`.

**In Claude Desktop / web** you can't set local files. Either:

- paste the token in the chat when Claude asks (used once, never saved; revoke
  it afterwards because it stays in the chat history), or
- skip the token: export the PRD/TD from Confluence (Tools → Export to
  PDF/Word), then attach the files and any screenshots to the chat.

Never commit or share a token.

## Usage

Give Claude both links, plus any screenshots/mockups you want used as context:

> Generate test cases from this PRD: <link> and this TD: <link>

- If you only have one doc, say so (PRD only → E2E sheet, TD only → API sheet).
- Attach images in the chat to include them in UI and flow verification.
- The result is `<feature-name> Test Cases.xlsx`, plus a short summary of
  coverage and any PRD-vs-image/TD conflicts found.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `TOKEN_MISSING` | Set up a token (see above) or use the export/attach fallback |
| 401 / 403 | Token expired or lacks access to the page; create a new one |
| Connection error with a valid token | The environment can't reach internal Confluence; use Claude Code locally or the attach fallback |
| `externally-managed-environment` on pip install | Use the venv: `python3 -m venv /tmp/tcgen-venv && /tmp/tcgen-venv/bin/pip install requests beautifulsoup4 openpyxl` |
| Upload rejected as a security issue | Remove `config.json` from the folder before zipping |
