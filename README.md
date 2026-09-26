# MCP Trust Score

[🇫🇷 Version française](./README.fr.md)

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)
![GitHub Action](https://img.shields.io/badge/GitHub%20Action-available-brightgreen.svg)

GitHub Action for compliance and availability checks on MCP (Model
Context Protocol) servers. It connects to an MCP server, verifies it
behaves correctly, and computes three complementary technical scores to
give a fast trust signal inside a developer's CI/CD flow.

## What it checks

On every run, the tool:
1. Connects to the given MCP server and verifies it responds correctly
   to the protocol (handshake, tool listing, resource listing)
2. Computes a **NIST score** — a heuristic self-assessment aligned with
   the 4 functions of the NIST AI RMF (Govern, Map, Measure, Manage)
3. Computes an **OWASP score** — technical signals inspired by 2 out of
   the 10 categories of the OWASP MCP Top 10 (MCP03: Tool Poisoning,
   MCP08: Lack of Audit and Telemetry)
4. Computes an **AXIOM score** — technical signals inspired by Domains 4
   and 5 ("Fiability/Security" and "Data & AI Technical Integrity") of a
   proprietary AI maturity framework
5. Can fail the CI job if the score falls below a configurable threshold

## ⚠️ What these scores are — and are not

None of these three scores are an official certification. They are
**heuristic self-assessments**, based on technical checks that can be
verified automatically (presence of descriptions, metadata, correct
protocol responses). They give a fast, useful signal — not a full
compliance audit. Neither the NIST AI RMF, the OWASP MCP Top 10, nor
AXIOM reduce to what a script can observe from outside an MCP server.

**OWASP coverage is intentionally limited.** The OWASP MCP Top 10 has 10
risk categories; this tool only covers 2 (MCP03, MCP08) — the ones a
one-off protocol check can meaningfully observe. The other 8 (token
mismanagement, privilege escalation, supply chain attacks, command
injection, intent flow subversion, auth/authz, shadow servers, context
oversharing) require real-time traffic inspection or deeper analysis —
out of scope for this tool. For that, see dedicated runtime security
scanners built specifically for the OWASP MCP Top 10.

This is also **not** a penetration-testing tool.

## Install in your own repo

Add this file at `.github/workflows/mcp-trust-score.yml`:

```yaml
name: MCP Trust Score

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  mcp-trust-score:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install dependencies
        run: pip install -r requirements.txt   # adapt to your project

      - name: Check MCP compliance
        uses: YOUR-USERNAME/mcp-trust-score@v1
        with:
          server-command: 'python3 my_server.py'
          min-score: '70'
```

## Inputs

| Name | Description | Default |
|---|---|---|
| `server-command` | Command to launch your MCP server | required |
| `min-score` | Minimum NIST score (%) required for the job to pass | `70` |
| `enable-blockchain-anchor` | Anchors a report hash on OpenTimestamps (Bitcoin) | `false` |
| `submit-to-leaderboard` | Automatically submits the score to the public leaderboard (the job needs `permissions: id-token: write`: the submission carries a GitHub OIDC token proving which repository it comes from) | `false` |
| `leaderboard-api-url` | Leaderboard API URL (required if `submit-to-leaderboard=true`) | `''` |

## Outputs

| Name | Description |
|---|---|
| `score` | NIST score (%) |
| `axiom_score` | AXIOM score (%) |
| `owasp_score` | OWASP score (%) — 2 out of 10 categories |
| `blockchain_proof` | Path to the `.ots` proof file, empty if disabled or failed |
| `passed` | `true`/`false` based on the `min-score` threshold |
| `reachable` | `true`/`false` based on whether the server responded |

## Traceability via OpenTimestamps anchoring

Set `enable-blockchain-anchor: true` in your workflow so that each run
computes a SHA-256 hash of the report (NIST + AXIOM scores, server name,
date) and anchors it on the Bitcoin blockchain via the open OpenTimestamps
protocol — free, no crypto wallet required.

✅ **Tested end to end**: verified working on a real GitHub Actions run
(network access to OpenTimestamps calendar servers, which local dev
sandboxes may lack, worked correctly on the GitHub-hosted runner). This
feature is designed to fail **silently** (never affects `passed`/job
success) if network anchoring fails — only `blockchain_proof` stays empty.

A freshly created proof is not immediately verifiable — it typically
needs a Bitcoin block confirmation (up to a few hours). Use
`ots upgrade <file>.ots` then `ots verify <file>.ots` later to confirm it.

## Public leaderboard

A public leaderboard of MCP servers by score, in `LEADERBOARD.md` and as
a static site at `docs/index.html` (free, hosted via GitHub Pages — no
server to maintain).

**To add your server**: open a Pull Request adding your entry to
`leaderboard/entries.json` (format shown in the file), with a score
obtained via this Action.

An **optional** automatic submission path also exists
(`submit-to-leaderboard` input) via a small hostable API
(`leaderboard/api.py`) — requires hosting it yourself (Render, Railway,
or a small VPS). Tested end to end locally: real HTTP submission, with
basic abuse protection (score bounds, hash consistency check, per-repo
rate limiting). Submissions must carry a GitHub Actions OIDC token
(`permissions: id-token: write`): the API uses the repository attested by
GitHub, not the one declared, and only such attested submissions are listed
and count toward EMMA/Silver tiers. Organizational audits can only be
submitted by auditors holding a token, and audit reports are served under
unguessable links.

⚠️ Scores on the leaderboard are self-reported by developers, not
audited by a third party. The blockchain proof (when present) only
guarantees the report wasn't modified after submission — not that the
initial score is accurate.

## Enable the static leaderboard site (GitHub Pages, free)

1. Repo → Settings → Pages
2. "Source" → "Deploy from a branch"
3. Branch `main`, folder `/docs`
4. Save

Your site will be live within a few minutes at
`https://YOUR-USERNAME.github.io/mcp-trust-score/`.

## Project structure

```
mcp-health-check/
├── action.yml                # GitHub Action manifest
├── run_action.py             # Entry point, orchestrates all checks
├── checker.py                 # MCP server connection + base checks
├── nist_score.py              # NIST AI RMF-aligned score
├── owasp_score.py             # OWASP MCP Top 10-aligned score (partial)
├── axiom_score.py             # AXIOM-inspired score (Domains 4 & 5)
├── blockchain_anchor.py       # Hash-based traceability (optional)
├── test_server.py             # Minimal MCP server for testing the Action
├── leaderboard/
│   ├── entries.json           # Public leaderboard submissions
│   ├── generate_leaderboard.py # Generates LEADERBOARD.md + docs/index.html
│   └── api.py                  # Optional hostable API for auto-submission
├── docs/
│   └── index.html             # Static leaderboard site (GitHub Pages)
└── action-package/
    ├── example-workflow.yml    # Example workflow to copy into a target repo
    └── update-leaderboard-workflow.yml  # Auto-regenerates the leaderboard
```

## Discoverability (Repo Topics)

For GitHub search visibility, add these Topics to the repo (Settings →
General → Topics, or the gear icon next to "About" on the main page):

`mcp` `model-context-protocol` `ai-agents` `compliance` `security`
`ci-cd` `github-action` `nist` `owasp` `ai-governance`

## License

MIT — see the `LICENSE` file. Free to reuse, modify, and redistribute,
including commercially, as long as the copyright notice is kept.

## Technical badge tiers (EMMA / Silver)

The public API (`leaderboard/api.py`) can compute two technical badge
tiers for a given server, based on its AXIOM technical score and
verification recurrence over time:

- **EMMA** *(Edge Methodology Management of AI)*: latest AXIOM technical
  score ≥ 70% (≈ passing 6 out of 8 checks)
- **Silver**: AXIOM score ≥ 80% (stricter than EMMA) on at least 3
  qualifying verifications, with at least 14 days between the first and
  last one, within a 30-day window — proves sustained compliance over
  time, not a burst of closely-spaced checks

```
GET /badge?repo_url=https://github.com/your-org/your-repo
```

✅ **Tested end to end**: verified across multiple scenarios including
the anti-gaming case — 3 closely-spaced submissions (all within days)
correctly stay at EMMA tier; only submissions genuinely spread across
≥14 days count toward Silver.

⚠️ **Scope**: these two tiers apply to the technical agent/server itself
(AXIOM Domains 4-5, already automated). Higher tiers evaluating the
*organization* publishing the agent (AXIOM's other domains — Strategy,
Governance, Accountability, etc.) would require a human-led audit
process, not yet built — see project notes for design discussion.

## Organizational audit (Gold / Platinum tiers) — AXIOM v1.1

The audit applies the **AXIOM v1.1** method: 9 domains, 27 sub-domains (including
"Agents & outils"), levels 0–4 with half-levels.

**Public part** (in this repo, `leaderboard/methodology/axiom_public_v1_1.json`, and on
the `/methodologie` page): domains and sub-domain titles, scale, evidence types and
their caps, scoring formula, tier criteria.
**Confidential part** (NOT in this repo): level descriptions, evidence rules, weights,
framework mappings. The server reads it from the file named by `AXIOM_METHODOLOGY_FILE`
(on Render: a Secret File). Without it, the audit is disabled; the public page still works.
Tests use a fictitious grid (`leaderboard/tests/fixtures/axiom_test_grid.json`).

- Each sub-domain gets a proposed level, the **type of evidence** obtained and a
  justification. The retained level is capped by the evidence (public source or
  interview: N2, document: N3, verified by the assessor or technical measurement: N4).
- Sub-domains 9.3, 9.4, 9.6 cannot go above N2 without a **technical measurement**.
- Score = Σ(retained level × weight) ÷ Σ(4 × weight) over evaluated sub-domains,
  always published with its weighted **coverage**.
- **Gold**: score ≥ 75% with coverage ≥ 80%. **Platinum**: Gold + a linked repo holding
  the technical **Silver** tier.
- The form (`/audit`) shows the confidential grid, so it is reserved to assessors
  (browser login: name + token from `AUDITOR_TOKENS`). Reports show the assessor, the
  methodology version, retained levels and capped levels — not the grid itself.

Audits recorded with the previous 11-question questionnaire are still readable.

## AI-assisted audit draft (local model only)

`leaderboard/ai_audit_assist.py` reads company documents (`.txt`, `.md`, `.pdf`) from a
data room folder and asks a **local model through Ollama** to propose draft levels,
one sub-domain at a time, citing the documents. Neither the client's documents nor the
grid leave the machine: the tool refuses a non-local Ollama server unless
`--allow-remote` is given. Drafts are capped with the same rules as the form.

```bash
ollama pull mistral-small            # or any model you prefer
export AXIOM_METHODOLOGY_FILE=/path/to/axiom_v1_1.json
python3 leaderboard/ai_audit_assist.py <data_room_folder> --model mistral-small
```

⚠️ **Draft only** — an assessor must review every level before entering it in `/audit`.
Local models are usually less reliable than large hosted ones.

## Automatic blockchain anchoring on tier progression

Badge certification is now anchored **automatically** — but only when
a repo's tier genuinely progresses (e.g., none → EMMA, or EMMA →
Silver), not on every submission that merely maintains the same tier.
This avoids spamming the blockchain with redundant certifications.

✅ **Tested end to end**: verified that a genuine progression (none →
EMMA) correctly triggers an anchoring attempt, and that a repeated
submission maintaining the same tier does not re-trigger it. The actual
network anchoring call fails gracefully in this dev environment (no
network access to OpenTimestamps calendars) but never breaks the score
submission response itself — same non-blocking pattern used elsewhere
in this project.

## Reference framework monitoring (OWASP / NIST / AXIOM)

The hosted server can track updates to the reference frameworks
themselves, so users know when their MCP Trust Score might be based
on an outdated version and should re-run their check.

- **OWASP MCP Top 10**: the most actively evolving of the three — still
  in beta (Phase 3), with a major update planned for October 2026 and
  periodic releases after that. ✅ **Tested with a real network call**:
  successfully fetched the latest commit SHA from the official OWASP
  GitHub repo.
- **NIST AI RMF**: a stable government framework, major revisions are
  rare. Monitored for consistency, but few alerts expected in practice.
  Confirmed the check code is correct; blocked only by this dev
  environment's network restrictions (not by NIST) — verify on a real
  deployment.
- **AXIOM**: controlled by the framework's author — updates are
  triggered manually (`framework_watch.trigger_axiom_update()`), not
  auto-detected, since there's no external source to poll.

```
GET  /framework-status     # see tracked versions and recent update events
POST /subscribe             # {"email": "you@example.com"} — free for now
```

Run `python3 framework_watch.py` periodically (e.g. daily via a
scheduled task) to check for updates and record change events.

⚠️ For production use, set a `GITHUB_TOKEN` environment variable — the
GitHub API is rate-limited to 60 requests/hour without authentication
(confirmed by hitting that exact limit during testing), 5000/hour with
a token.

## ⚠️ Important: what framework detection does NOT do

Detecting a framework update **does not automatically update the
scoring logic** (`nist_score.py`, `owasp_score.py`, `axiom_score.py`).
It's a "go check this" signal, not an automated code update — turning
a real framework change into new scoring rules requires human judgment
(same principle applied to the AI-assisted audit: draft, never
auto-applied).

✅ **Tested**: `/framework-status` now returns an actionable `change_url`
(direct link to the OWASP commit) and `change_summary` (commit message)
for each detected change — verified end to end against real PostgreSQL.
For NIST, no per-change link is possible (no public version history
API) — only a link to the page itself, to check manually.

## Automatic daily framework check (cron)

Instead of relying on manual `curl` calls, a scheduled GitHub Action
(`action-package/framework-watch-cron.yml`) triggers `/framework-check`
automatically once a day — reusing GitHub Actions (already free and in
use in this project) instead of a separate paid cron service.

✅ **Tested**: YAML syntax and cron expression validated (`0 8 * * *` =
daily at 08:00 UTC). The actual scheduled trigger itself can only be
confirmed once installed on GitHub (schedules don't run locally).

### Install it

Copy `action-package/framework-watch-cron.yml` to
`.github/workflows/framework-watch-cron.yml` in your repo, then push.
You can also trigger it manually anytime from the Actions tab
(`workflow_dispatch` is enabled) to test without waiting a full day.

## Public companies certification page (Gold / Platinum)

A gap was identified and fixed: Gold/Platinum tiers were computed and
stored, but never displayed anywhere publicly (unlike the technical
EMMA/Silver badges, visible on the leaderboard). Added:

```
GET /companies       # HTML page listing all Gold/Platinum companies
GET /companies.json  # same data, JSON
```

✅ **Tested end to end against real PostgreSQL**, including the full
Platinum case (organizational audit + linked repo holding technical
Silver tier) — both correctly displayed, sorted by tier then score.

## Redesigned organizational audit (radar chart, full report)

Following user feedback that the original audit form felt too basic
for a serious self-assessment tool, it was completely redesigned:

- **Professional visual design** — card-based layout, color-coded score
  selectors, proper typography, instead of plain dropdowns
- **Evidence field per question** — auditors document proof/justification,
  not just a bare score
- **Full HTML report page** (`/audit-report/<id>`) generated after
  submission, instead of a bare JSON response, including:
  - Overall maturity score and tier badge
  - **Radar chart** (pure SVG, no external JS library dependency) showing
    the score per domain
  - Automatically identified **strengths and weaknesses** (top/bottom
    scoring domains)
  - Full detail with evidence, color-coded by score

✅ **Tested end to end against real PostgreSQL**: form renders with new
fields, submission with varied scores + evidence stored correctly,
report page generates with correct radar SVG, strengths/weaknesses, and
evidence text displayed. Radar chart geometry was verified mathematically
(exact coordinate checks for known angles/percentages) before integration.

⚠️ Two real bugs were introduced and caught during this session by
checking function lists after each edit (not assuming success) — a
recurring lesson applied consistently throughout this project's history.
