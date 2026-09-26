# Data Room — AI-assisted audit draft (local model)

Drop company documents here (AI policies, charters, RSE/sustainability
reports, governance meeting notes, etc.) to have a **local** model (Ollama)
propose a DRAFT level for each sub-domain of the AXIOM v1.1 grid.
Nothing leaves your machine. Do not commit real client documents.

## Structure

```
data_room/
└── <company-name>/
    └── documents/
        ├── ai-charter.txt
        ├── rse-report.pdf
        └── governance-notes.md
```

Supported formats: `.txt`, `.md`, `.pdf`.

## Usage

```bash
pip install requests pypdf
ollama pull mistral-small                       # any local model
export AXIOM_METHODOLOGY_FILE=/path/to/axiom_v1_1.json   # confidential grid
python3 ai_audit_assist.py data_room/<company-name>/documents --model mistral-small
```

This produces `draft_audit_result.json` in that folder — a **draft**,
not a final audit.

## ⚠️ Critical: this is AI-assisted, not AI-decided

- The AI is instructed to score ONLY what's explicitly present in the
  documents — no inference of "plausible" good practices.
- Any question not covered by the documents gets `confidence:
  "aucune_preuve"` (no evidence) and a score of 0 by default.
- **A human must review every proposed score** before entering it into
  the official audit form (`/audit`, AXIOM v1.1 grid). This tool accelerates
  document review — it does not replace the auditor's judgment.
- Tested with a simulated Ollama server; not yet run against a real local model.

## Example

The `exemple-entreprise/documents/` folder contains sample documents
you can use to test the pipeline once you have an API key.
