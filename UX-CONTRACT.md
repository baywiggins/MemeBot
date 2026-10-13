# Workbench interaction contract

Business authority: docs/IMPLEMENTATION.md and the approved user plan. Visual authority: DESIGN.md.

## Canonical UI Map
| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox | Streamlit selectbox/radio | DESIGN.md | authored library control | AppTest and browser keyboard |
| Date | Streamlit date_input | America/New_York calendar day | authored library calendar | date-window tests and browser |
| Form | Streamlit form with shared error feedback | service validation | source / metadata / settings | AppTest invalid submit |
| Scrollbar | ui_components shared stylesheet | DESIGN.md theme.json | document / bounded table | browser |
| Toast | shared flash + persistent inline alerts | ui_components | success / error / info | AppTest |
| CRUD | Episodes service + Store | revision and approval contract | create / edit / exclude | test_episodes.py |

## Navigation and state
Five sidebar views share page spacing and controls. Save keeps the current item selected. Date and selected episode live in query parameters; transient clip-page selection and form input live in Streamlit session state (single-user local tool). Controls are labeled. A job submission is deduplicated and immediately acknowledged. Source/library tables are bounded; clip previews paginate twelve at a time.

## Actions and recovery
Read-only review never sends anything to YouTube. Collect and Render enqueue durable work. Approval checks the current artifact hash, revision, and 5–10 minute duration. Upload privately needs approval and a connected channel; Publish is a separate explicit action naming the destination. Upload uncertainty stays visible and blocks fresh upload creation. Reconciliation verifies destination and the episode's private metadata tag. Published episodes and active uploads cannot be edited.

Errors are inline and remain available in the job history. Refresh reloads durable state. SQLite revision conflicts preserve database truth and ask the stale session to refresh. Background collection preserves successful sources even when another fails. Native browser dialogs are not used. No automatic public posting. Live job display polls only job state, and full-page refresh occurs only on job completion.

## Accessibility and local operation
Streamlit supplies semantic labeled controls, accessible authored popups, focus treatment and browser media controls. Reordering has Up/Down alternatives. Narrow layouts stack. No essential animations. No remote fonts. All credentials are masked and saved only in owner-readable files outside the repository. Bind to localhost; remote/multi-user deployment is outside this contract.
