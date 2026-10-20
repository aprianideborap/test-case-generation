---
name: test-case-generation
description: Generate a QA test-case spreadsheet from a PRD Confluence link and a TD (Technical Design) Confluence link. Use this whenever the user pastes Confluence link(s) (or asks to generate/write test cases "from this PRD/TD/spec/link/images/files") and wants test cases produced from them. Also trigger on requests like "buatkan test case dari confluence ini", "generate test case untuk fitur ini", or any ask to turn Confluence requirements/design docs into test cases, even if they don't name the output format explicitly. Produces both E2E test cases (grounded in the PRD) and API test cases (grounded in the TD) with thorough edge-case and negative-case coverage. Always fetch actual page content via the bundled Confluence REST API script rather than guessing from a URL or title alone.
---

# Test Case Generation from Confluence (PRD + TD)

Turn a pair of Confluence docs — a PRD (product requirements) and a TD
(technical design) — into a structured test-case spreadsheet (.xlsx) with two
sheets, E2E and API, and hand the file back to the user.

## Why this exists

Test cases are only as good as their grounding in the actual spec. The point of
this skill is to read the *real* Confluence content (not just infer from the
page title or the user's paraphrase) so the test cases reflect what's actually
written — acceptance criteria, edge cases, platform-specific behavior, request/
response contracts, etc. The PRD and TD answer different questions: the PRD
describes what the user experiences (drives E2E cases), the TD describes how
it's built underneath — endpoints, payloads, validation rules, error codes
(drives API cases). Reading only one of the two leaves a gap: PRD-only misses
API-level edge cases the user never sees; TD-only misses whether the behavior
actually satisfies the product requirement.

## One-time setup

The fetch script authenticates to `confluence.shopee.io` with a Personal
Access Token (Server/Data Center Bearer auth). It looks for the token in this
order: the `CONFLUENCE_TOKEN` env var (optionally `CONFLUENCE_BASE_URL`),
then `~/.config/confluence/config.json`, then a gitignored `config.json` in
the skill folder (copy of `config.example.json`). Never ship a real token
inside the skill folder.

**If no token is found** the script exits with a `TOKEN_MISSING` message.
Don't guess at the page content. Instead, tell the user, in their language:
1. The token isn't set up yet, and where it looked.
2. How to create one: confluence.shopee.io -> profile avatar -> Personal
   Access Tokens -> Create token (suggest a short expiry).
3. They can either set it themselves (`export CONFLUENCE_TOKEN=...` or the
   user-level config file), or, if they're in a chat environment with no
   local shell access, paste it into the chat.

**No-token fallback:** the user can instead export the PRD/TD from Confluence
(Tools -> Export to PDF/Word) or paste the page text, and attach them to the
chat along with any screenshots. Read those attachments directly and skip the
fetch script; everything else in the workflow (images as context, conflict
notes, edge cases) stays the same. Offer this whenever the token can't be
set up or Confluence is unreachable from the environment.

If the user pastes a token: use it only for the fetch, by passing it as the
`CONFLUENCE_TOKEN` env var on the command (or a temp config in the scratchpad
directory, deleted afterward). Never write it into the skill folder, never
echo it back in replies or the spreadsheet, and remind them to revoke it
when they're done since it now exists in the chat history.

## Workflow

1. **Get both links: PRD and TD, plus any images.** The user may also attach
   images in the chat (screenshots, mockups, flow diagrams) or give image
   file paths — if any are present, treat them as required context for every
   test case (see step 3). If an attached image isn't visible to you, ask the
   user to resend it rather than skipping it. If the user only gives one link, ask which doc
   is missing rather than assuming — E2E cases need the PRD, API cases need
   the TD, and skipping either link means skipping that whole test type. If
   the user explicitly says they only want one test type (e.g. "just API
   tests"), it's fine to proceed with just that link.

2. **Fetch both pages via the REST API script, not WebFetch, and pull any
   embedded images too.** Confluence pages require authentication, so a plain
   WebFetch will fail or return a login wall. Use the bundled script once per
   link, always passing `--images-dir` — PRDs commonly embed screenshots or
   flow diagrams directly in the page (not just as Figma links), and those
   only become usable once downloaded as real files:

   ```bash
   python3 scripts/fetch_confluence_page.py --url "<the PRD link>" --images-dir /tmp/prd-images
   python3 scripts/fetch_confluence_page.py --url "<the TD link>" --images-dir /tmp/td-images
   ```

   - It resolves the page from the URL (handles `?pageId=`, `/pages/<id>/...`,
     and `/display/SPACE/Title` link formats), calls
     `GET {base_url}/rest/api/content/...?expand=body.storage`, and prints the
     page as readable markdown (headings, lists, and tables preserved).
   - Every image referenced in the body (Confluence's `ac:image` macro, or a
     plain `<img>`) shows up inline as `[IMAGE: filename.png]` exactly where
     it appears in the text, so you know which section each one illustrates.
     With `--images-dir`, those images are also downloaded as real files, and
     the output lists each one's local path under "Embedded Images".
   - **View every downloaded image with the Read tool before drafting cases.**
     A screenshot or flow diagram often shows UI details — exact labels,
     buttons, tabs, badges, layout, states — that the PRD's prose never spells
     out. Skipping this step means missing exactly the kind of detail this
     skill exists to catch.
   - If it errors with a missing/invalid dependency, install into the shared
     venv (see step 5 for why a venv, not a bare `pip install`):
     ```bash
     python3 -m venv /tmp/tcgen-venv 2>/dev/null || true
     /tmp/tcgen-venv/bin/pip install --quiet requests beautifulsoup4
     /tmp/tcgen-venv/bin/python3 scripts/fetch_confluence_page.py --url "<the confluence link>" --images-dir /tmp/prd-images
     ```
   - A 401/403 means the token in `config.json` is missing, expired, or
     lacks access to that page — tell the user to refresh it rather than
     guessing at the content.
   - Read the full body of both pages, not just a summary — test case quality
     depends on catching details buried in tables, bullet lists, and
     acceptance criteria sections.

3. **Read each doc for what it's good at, not the same way twice.**

   **PRD → E2E test cases.** Look for:
   - Distinct user flows / interactions (each usually becomes 1+ test cases)
   - Explicit acceptance criteria or "should/must" statements
   - Platform differences (Desktop / Android / iOS) — the E2E sheet tracks
     results per platform, so note where behavior is expected to differ
   - A natural module/feature hierarchy (e.g. "Composer > Dropdown > First-Level")
     to fill the Module 1-5 columns — leave unused module levels blank rather
     than forcing 5 levels
   - **UI & flow verification from images (mandatory whenever any image
     exists)** — images come from two sources: embedded in the Confluence
     pages (step 2) and attached by the user in the chat or given as a file
     path. View all of them with the Read tool and use them as context for
     every test case, not just the UI ones. Always include E2E cases that
     verify the UI and the flow shown:
     - **One UI case per visible element group**: every menu, tab, filter,
       button, badge, card, label, dropdown, empty state, and the layout/
       ordering shown in the image gets a case verifying it is displayed with
       the exact label, position, and state (enabled/disabled/selected).
       Example: if the image shows a "Skills" menu, add a case that verifies
       the "Skills" menu exists, where it sits, and that it opens the right
       page.
     - **One flow case per screen-to-screen path** shown in a flow diagram or
       sequence of screenshots, verifying each transition and the screen
       reached.
     - **PRD wins on conflicts.** If the image and the PRD disagree (different
       label, missing/extra element, different behavior or ordering), write
       the test case following the PRD only, and record the discrepancy in
       the `remarks` field (the Remarks column) in this form:
       `Note: PRD vs image mismatch — PRD says "<X>", image shows "<Y>".
       Test case follows PRD.` Do the same for TD vs PRD conflicts.
     - If an image is purely illustrative and adds nothing testable, say so in
       the final summary instead of silently ignoring it.

   **TD → API test cases.** Look for:
   - Every endpoint/operation described (method, path, request/response shape)
   - Field-level validation rules (required/optional, types, length/range
     limits, enums, formats like email/date) — each rule implies at least one
     negative case
   - Auth/authorization requirements (missing token, expired token, wrong
     role/permission)
   - Error codes and status codes the TD defines, and what triggers each one
   - State/dependency assumptions (e.g. "SKU must exist", "order must be in
     PENDING status") — each implies a negative case for the assumption being
     violated

   **Edge and negative cases are not optional** — this skill exists
   specifically to cover them thoroughly, not just the happy path. For every
   flow/endpoint, deliberately think through: boundary values (empty, zero,
   negative, max length/size, one-past-max), malformed/missing/extra input
   fields, wrong data types, duplicate/idempotent requests, concurrent
   requests on shared state, permission and auth failures, dependency/state
   violations (e.g. acting on a deleted or already-processed resource), and
   timeout/partial-failure behavior where the TD discusses it. Not every spec
   will have material for all of these — use judgment — but check each
   category rather than stopping once a few obvious happy-path cases exist.

   **Make edge cases scenario-specific, never generic.** Don't write
   "invalid input" or "unauthorized user". Ask "what concrete things could
   go wrong in *this* feature, given what the PRD, TD, and images say?" and
   write one case per realistic scenario, naming the concrete input or
   condition. Example — a feature to upload a skill via GitHub link should
   expand into scenarios such as:
   - link is not a GitHub URL (e.g. gitlab.com or a random domain)
   - GitHub repo is private / the user has no access
   - repo or path does not exist (404), or branch/tag does not exist
   - repo has no SKILL.md, or SKILL.md has missing/invalid frontmatter
   - repo exceeds the size limit, or contains a disallowed file type
     (e.g. executable, binary)
   - content fails the security check (e.g. embedded secrets/tokens,
     malicious or prompt-injection instructions, suspicious scripts, path
     traversal in file names) — one case per kind of violation the PRD/TD
     lists
   - same skill name already exists (duplicate), or a name that is
     reserved/too long/has special characters
   - GitHub API rate-limited or unreachable mid-import (partial failure:
     nothing half-saved)
   - user lacks permission to upload, or the session expires mid-upload
   Apply the same depth to every other feature: derive the scenarios from the
   specific fields, limits, statuses, roles, and rules actually written in the
   docs/images, and use the real limit values (e.g. "51 characters" when the
   max is 50) in the case.

   **Preconditions must be concrete, not generic.** Write exactly the state
   the tester must set up before step 1 for *that* case, e.g. "User is logged
   in as a Workspace Admin; no skill named 'demo-skill' exists yet; a public
   GitHub repo containing a valid SKILL.md is available" — not "User is logged
   in" or "System is running". Include role/permission, required existing
   data (or its absence), feature flags/settings, platform/app version, and
   the screen the user starts on when relevant. Steps must be equally
   specific: name the exact menu/button/field labels (from the PRD and
   images) and the exact test data to enter.

4. **Draft the test cases as JSON**, split into `"e2e"` and `"api"` lists in
   one object:

   ```json
   {
     "e2e": [
       {
         "no": 1,
         "test_case_name": "Open Capability list via @ in composer",
         "modules": ["Dropdown", "First-Level"],
         "priority": "P0",
         "precondition": "Composer is empty and focused.",
         "steps": "1. Click composer\n2. Type '@'",
         "expected_result": "- Combined dropdown opens showing 2 sections in fixed order: Chat context, Connectors\n- Highlights the SeaTalk chats by default",
         "result": {"desktop": "", "android": "", "ios": ""},
         "remarks": ""
       }
     ],
     "api": [
       {
         "no": 1,
         "test_case_name": "Reject order creation with negative quantity",
         "modules": ["Orders", "Create"],
         "priority": "P0",
         "precondition": "Valid auth token, existing product SKU.",
         "method": "POST",
         "endpoint": "/api/v1/orders",
         "request_payload": "{\"sku\": \"ABC123\", \"quantity\": -1}",
         "steps": "1. Send POST /api/v1/orders with negative quantity",
         "expected_status_code": "400",
         "expected_result": "Response contains error code INVALID_QUANTITY; no order created.",
         "result": "",
         "remarks": ""
       }
     ]
   }
   ```

   - `priority`: P0 (core/blocking flow), P1 (important but not blocking),
     P2 (minor/cosmetic) — infer from how central the behavior is to the
     feature described.
   - `result` / `result.*`: leave blank (not "Failed"/"Passed") unless the
     user tells you these test cases have already been executed — this skill
     generates cases, it doesn't run them.
   - Write `steps` and `expected_result` as newline-separated, numbered/bulleted
     text — that's what renders cleanly in the spreadsheet cell.
   - Omit the `"e2e"` or `"api"` key entirely (or leave it an empty list) if
     that test type genuinely doesn't apply (e.g. no TD was given).
   - Save this JSON to a temp file (e.g. in the scratchpad directory).

5. **Generate the spreadsheet** with the bundled script — don't hand-roll
   openpyxl code each time:

   ```bash
   python3 scripts/generate_xlsx.py --input cases.json --output "<feature-name> Test Cases.xlsx"
   ```

   If this (or the fetch script in step 2) fails with a missing-module error,
   `pip3 install <package>` may hit a PEP 668
   "externally-managed-environment" error on Homebrew/system Python. Don't
   reach for `--break-system-packages` on a shared interpreter — use one
   shared throwaway venv for both scripts instead:
   ```bash
   python3 -m venv /tmp/tcgen-venv 2>/dev/null || true
   /tmp/tcgen-venv/bin/pip install --quiet requests beautifulsoup4 openpyxl
   /tmp/tcgen-venv/bin/python3 scripts/generate_xlsx.py --input cases.json --output "<feature-name> Test Cases.xlsx"
   ```
   The venv persists at `/tmp/tcgen-venv`, so later runs in the same session
   (or later invocations of this skill) can skip straight to the `pip install`
   (fast no-op once already installed) + run step.

   This writes one workbook with up to two sheets:
   - **E2E Test Cases**: No, Test Case Name, Module 1-5, Priority, Precondition,
     Test Steps / Prompt, Expected Result, Result (merged header over
     Desktop/Android/iOS), Remarks.
   - **API Test Cases**: No, Test Case Name, Module 1-5, Priority, Precondition,
     Method, Endpoint, Request Payload, Test Steps / Prompt, Expected Status
     Code, Expected Result, Result, Remarks.

   Both sheets get header styling, wrapped text, and frozen header rows. A
   sheet is only created if its list in the input JSON is non-empty.

6. **Hand back the file** and briefly summarize what was covered per sheet
   (how many cases, which flows/endpoints/platforms, which images were
   factored in and how many UI/flow cases came from them, a list of every
   PRD-vs-image/TD conflict found (also noted in Remarks), and which
   edge/negative scenarios were covered), so the user can quickly sanity-check
   coverage against the source docs.

## Notes

- If either doc is large or covers multiple unrelated features, ask the user
  whether they want test cases for the whole doc or a specific section —
  don't silently generate cases for only part of it.
- If a doc's content is thin (e.g. just a title, no real spec), say so rather
  than inventing requirements that aren't in the page.
- If an image fails to download (e.g. `--images-dir` warns an attachment
  wasn't found), don't block the whole run on it — note which image is
  missing and proceed with the rest.
