# SDLC Document Templates

The PULSE document-generation pipeline (`pipeline/run_pipeline.py` →
`pipeline/fill_template.py`) reads DOCX templates from this folder and
fills them with content the AI agents extract from your codebase, RAG
corpus, and integrated systems.

> **The 10 production templates are not bundled with this repo.** Two
> minimal sample templates are provided so you can see the structural
> conventions `fill_template.py` expects. Use them as a reference and
> drop your own production templates into this folder before running
> the pipeline.

---

## What's bundled

| File | Purpose |
|------|---------|
| [CPDD_Template.docx](CPDD_Template.docx) | Sample Comprehensive Project Definition Document — minimal placeholder |
| [Architecture_and_Design_Template.docx](Architecture_and_Design_Template.docx) | Sample Architecture & Design Document — minimal placeholder |

Both samples are skeletal: a header table, a few section-level key-value
tables, and a placeholder note. They are sufficient for the pipeline to
run end-to-end, but the output will not look like a real production
document until you replace them.

---

## Full template manifest (expected by the pipeline)

`pipeline/fill_template.py` registers the following filename mapping
(see `TEMPLATE_FILES` and `OUTPUT_NAMES` in that file). Drop a DOCX
matching each filename into this folder.

| Doc key | Template filename | Output prefix | Description |
|---------|-------------------|----------------|-------------|
| `cpdd` | `CPDD_Template.docx` | `CPDD` | Comprehensive Project Definition Document — project charter |
| `dor` | `DOR_Template.docx` | `Definition_of_Ready` | Definition of Ready — sprint-entry criteria |
| `architecture` | `Architecture_and_Design_Template.docx` | `Architecture_and_Design` | System architecture & design (arc42 / C4-style) |
| `risk_register` | `Risk_Register_and_Mitigation_Template.docx` | `Risk_Register` | Risk register with probability/impact and mitigations |
| `dod` | `Defination_Of_Done_Template.docx` | `Definition_of_Done` | Definition of Done — completion criteria |
| `runbook` | `Release_and_deployment_runbook_Template.docx` | `Release_Runbook` | Release & deployment runbook |
| `sop` | `SOP_Template.docx` | `SOP` | Standard Operating Procedure |
| `sprint_log` | `Sprint_Retro_Log_Template.docx` | `Sprint_Log` | Sprint ceremony & retrospective log |
| `project_explanation` | `Project_Explanation_Template.docx` | `Project_Explanation_Onboarding_Guide` | Project explanation / onboarding guide |
| `codebase_kb` | `Codebase_KB_Change_Versioning_Template.docx` | `Codebase_KB_Change_Versioning` | Codebase knowledge base & change versioning |

> **Note on the misspelling.** The filename `Defination_Of_Done_Template.docx`
> ("Defination") is intentional — `pipeline/fill_template.py` matches that
> exact filename. If you fix the typo in the template name, you must also
> fix it in the `TEMPLATE_FILES` dict in `pipeline/fill_template.py`.

---

## Structural conventions

`pipeline/fill_template.py` does not require any specific styling — only
the following structural conventions:

### 1. Table 0 — Header block
The **first table** in the document is treated as the header block. Its
right-most cell contains paragraphs of the form `Key: Value` that the
pipeline updates with the document metadata (Doc ID, Project, Version,
Date, Status, Owner, etc.). The keys it knows about are listed in
`_update_header_block()`'s `aliases` dict in `pipeline/fill_template.py`.

### 2. Section tables — Key-value layout
Subsequent tables are filled with extracted field values. The pipeline
supports two layouts:

* **2-column `[label][value]`** — every row has the field name in the
  first column and an empty (or placeholder) cell in the second column
  that the pipeline overwrites.
* **4-column `[label][value][label][value]`** — same as above but
  paired horizontally for compact layouts.

The pipeline matches your column-1 labels against the field names
extracted by the LLM via fuzzy matching (case-insensitive, token
overlap, prefix match). Spelling matters less than keyword overlap.

### 3. Data tables — Header row + data rows
For tabular sections (e.g. ADRs, Risks, Stakeholders), use a table
where row 0 is a header row and rows 1+ are data rows. The pipeline
reads the column headers and fills each row with extracted bullet-row
data. New rows are added automatically when the LLM returns more
items than the template has rows.

---

## How to add your own templates

1. **Author your DOCX** in Word (or generate via `python-docx`).
2. **Match the filename** to the entry in `pipeline/fill_template.py`'s
   `TEMPLATE_FILES` dict.
3. **Use the structural conventions** above so the pipeline can find
   and fill the right cells.
4. **Test by running the pipeline**:
   ```bash
   cd pipeline
   python run_pipeline.py --doc cpdd --project-name "MyProject"
   ```
   Inspect the generated DOCX in `pipeline/<MyProject>_ProjectDocs_<date>/`.

If the pipeline complains about a missing template file, check that
the filename matches the dict exactly (including the misspelling note
above).

---

## Why are templates not bundled?

The 10 production templates from the original hackathon project were
authored to match a specific organisation's documentation standards,
which I am not able to redistribute. The two minimal samples here are
authored from scratch by me and exist so the structure of this repo
matches what `pipeline/fill_template.py` expects out of the box.
