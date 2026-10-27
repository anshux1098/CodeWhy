# CodeWhy Frontend Design

## Purpose and scope

CodeWhy is a repository decision-archeology interface. It helps engineers investigate why code exists, inspect the historical decisions related to it, and follow the evidence and lineage behind those decisions.

This document describes the currently implemented frontend: its shared shell, navigation, pages, user interactions, responsive behavior, loading or empty states, and visual system.

## Visual system

The interface uses the warm light palette from the provided forensic workbench reference. Existing page structure and interactions are unchanged.

- **Canvas and surfaces:** canvas `#fff7f2`; base surface `#fffaf7`; cards `#ffffff`; raised and hover surfaces `#fff2eb` and `#ffe9df`; borders `#f4d8cc`.
- **Text:** primary `#161c2b`, supporting `#465268`, and muted labels `#778196`.
- **Primary action:** coral `#f0442b`, with a `#f65a3b` to `#e33d28` action gradient.
- **Semantic accents:** entity references use cyan `#148bd0`; verified evidence uses emerald `#07966b`; rationale and supersession cues use amber `#e9930b`; refusals use rose `#e83d54`.
- **Typography:** Inter is used for headings and body text; JetBrains Mono is used for code, identifiers, and compact metadata.
- **Use of color:** status and evidence accents communicate meaning; they are not decorative substitutes for labels or text.

## Application shell

The application uses a shared shell around all pages:

1. **Top navigation bar**
   - The CodeWhy logo returns to the Overview page.
   - Shows the active repository and marks fixture repositories.
   - Shows API connectivity and response latency when available; fixture mode is indicated when the API is not connected.
   - The **Switch Repo** action opens the repository selector.
2. **Side navigation**
   - Provides the six primary destinations listed below.
   - Can be expanded or collapsed. Its open state is saved in browser storage.
   - On smaller screens, the open sidebar overlays the page; choosing a destination closes it.
3. **Main content**
   - Renders the selected page while preserving the shared navigation.
4. **Footer**
   - Includes the brand description, product guarantees, and copyright statement.
5. **Repository selector dialog**
   - Available from the top bar and overlays the current page.

The selected repository is shared across repository pages and saved in browser storage. Switching repositories updates repository-specific routes and clears question context when the repository changes.

## Navigation tabs and routes

| Sidebar tab | Purpose | Route |
| --- | --- | --- |
| **Overview** | Introduces CodeWhy and starts an investigation. | `/` |
| **Investigate** | Ask a question about a repository and inspect the answer and evidence. | `/r/:repositoryId` or `/r/:repositoryId/investigate` |
| **Decisions** | Browse decision history associated with the current investigation. | `/r/:repositoryId/decisions` |
| **Before You Change** | Search for a file and review its linked decisions before editing it. | `/r/:repositoryId/file` |
| **Knowledge Graph** | Explore the graph associated with the latest investigation. | `/r/:repositoryId/graph` |
| **Repo Status** | Inspect repository ingestion, extraction, graph, and service telemetry. | `/r/:repositoryId/status` |

Repository IDs in routes are URL-encoded. Browser back and forward navigation updates the selected page.

## Pages

### Overview

The Overview page is the product landing and entry point to an investigation. It is organized vertically:

1. **Hero introduction**
   - Product identity and short explanation of the goal: find the reasoning behind code, not only its author.
   - **Start Investigating** opens the Investigate page.
2. **Product guarantees**
   - Three cards explain decision rationale discovery, verbatim quote verification, and principled refusal when evidence is insufficient.
3. **Pipeline architecture**
   - Five ordered stages explain how repository history becomes decision evidence:
     1. Target ingestion
     2. Noise elimination
     3. AST entity mapping
     4. Verbatim quote validation
     5. Decision lineage graph

The top navigation remains available so users can select a repository before or during navigation.

### Investigate

The investigation workspace is a repository-scoped question-and-answer console.

**Layout**

- A compact context bar identifies the investigation target and marks fixture data.
- The main answer area occupies the central workspace.
- When a response has been returned, an evidence-receipts margin appears beside the answer on wide screens and below it on narrow screens.
- A persistent question input bar sits at the bottom of the workspace.

**Starting a question**

- Users enter a question in the bottom input and submit it with the action button or Enter.
- Questions shorter than three characters cannot be submitted.
- The request may include an optional entity ID to focus the investigation.
- The Overview page can send an initial question to this page; it is automatically submitted when provided.

**Answer and response states**

- **Before asking:** an introductory console prompt explains what kinds of history the workspace can reconstruct.
- **Loading:** a progress card explains that the system is resolving entities, verifying quotes, and scoring provenance.
- **Error:** a backend error card displays the returned error message.
- **Full answer:** presents the answer, confidence score, identified entity and governing-decision count when available, citations, and a copy action.
- **Partial answer:** presents the available response, reason code and confidence when provided, and a notice that verified rationale is missing.
- **Principled refusal:** shows the refusal text and reason code, with a note that speculative history is not invented.
- **Ambiguous entity:** offers candidate entities as selectable cards. Choosing one sets the entity and resubmits a focused question.

Confidence details can be expanded to inspect individual signals.

**Citations and evidence**

- Citation chips in the answer select and focus the matching receipt.
- The Evidence Receipts margin lists verified quotes with citation ID, source link, author, and timestamp when available.
- Receipts can be copied, focused, or used to open their governing decision.
- Evidence gaps are shown separately when the backend reports missing historical records.
- A **Who to ask** section appears only when recommendations are returned.

### Decisions

The Decisions page presents the decision lineage associated with the latest investigation for the selected repository; it is not an unscoped repository-wide list.

**Context and filtering**

- A header identifies the repository and displays the number of visible decisions.
- When available, a context card shows the originating question and its target entity.
- State filters include All, Active, Superseded, Rejected, and Unresolved, with state counts when available.
- A text filter matches decision summaries, entity identifiers, and decision IDs.
- A callout clarifies that a newer decision is not considered superseding unless explicit lineage evidence supports that relationship.

**Timeline and details**

- Decisions appear as chronological cards connected by a visual timeline spine.
- Each card communicates state, summary, date, rule, source, and related entities when present.
- Selecting a card opens the shared decision detail drawer.
- Loading, request failure, no matching decisions, and no-investigation-context states are handled separately. The no-context state directs users to Investigate.

### Before You Change

This page creates a file-level decision brief to help users review historical context before editing a file.

**File search**

- Users search repository files by name or entity label.
- Search is debounced; matching file entities appear in a scrollable result list with path, ID, and linked-decision count.
- Selecting a result displays its path and entity ID and loads repository decision history.
- Search errors, no matches, loading, and initial instructions are shown inline.

**Decision brief**

The page explicitly distinguishes decisions linked to the selected file from general repository history. Only decisions whose entity list contains the file count as supported evidence for that file. The brief includes:

1. **Supported governing decisions:** active decisions explicitly linked to the file.
2. **Reverted / rollback decisions:** linked decisions whose rule or summary explicitly identifies a revert or rollback.
3. **Rejected decisions:** rejected decisions explicitly linked to the file.
4. **Recent active decisions:** up to four recent active repository decisions, each labeled as linked or unlinked to the file.
5. **Suggested reading order:** linked decisions ordered oldest-first while respecting explicit supersession relationships where available.

Each decision item shows its state, ID, date, summary, superseded IDs when present, and a source link when available. A final note reports how many linked decisions informed the reading order. History failures offer a retry action.

### Knowledge Graph

The graph page visualizes the repository subgraph related to the latest investigation. It starts with an instructional empty state and a link to Investigate if there is no matching question context or focus entity.

**Graph controls and content**

- Entity search finds graph entities and can be used to focus the graph on a selected entity.
- Users can switch between an interactive graph and an accessible list representation.
- Node-type filters cover the repository, code entities, decisions, pull requests, evidence, and people. Evidence and people are hidden by default.
- The graph lays nodes out in a top-to-bottom flow; edges describe relationships such as `SUPERSEDES`, `GOVERNS`, and `DECIDED_IN`.
- A legend explains the node and relationship types when a focused graph is displayed.
- Selecting a node opens its details; decision nodes can open the shared decision drawer.
- The graph includes navigation controls for moving around and zooming the visualization.

**Graph states**

- Loading, offline service, missing repository or entity, and general request error states are distinct.
- If the result is truncated, a notice explains that the returned graph reached the node limit and that some entities or lineage may be omitted.
- Development/test controls can simulate an unavailable graph response or a truncated result.

### Repo Status

The Repo Status page is a telemetry dashboard for the selected repository and its processing services.

**Header and polling**

- The header reports whether the API is online and describes the view as repository telemetry and provenance pipeline status.
- **Poll Now** triggers an immediate refresh.
- Health, dependency, and repository data are refreshed automatically every 30 seconds.
- The active engine version, data-source mode, last poll time, latency, and automatic-poll status are shown in the polling summary.

**Dashboard sections**

1. **Archeology pipeline lifecycle**
   - Three connected stages summarize Ingest, Extract, and Graph.
   - Ingest reports pull-request and commit counts, plus fetched-source details when returned.
   - Extract reports decision counts, extraction version, verified decisions, and skipped noise when returned.
   - Graph reports entity counts, active backing store, and whether a remote Neo4j service is configured or local SQLite mode is in use.
2. **Persistence and storage resilience**
   - Summarizes the active data source, graph query engine, and stated query availability.
3. **Configured services and dependencies**
   - Displays one card per reported dependency with its configuration status and details.
   - Shows a waiting message when dependency telemetry is not yet available.
4. **Available query outcomes and protocol responses**
   - Explains the supported full, partial, refusal, and ambiguous-entity outcomes.

## Shared overlays and controls

### Repository selector

The repository selector is a modal dialog with a title, explanatory subtitle, close control, and two internal tabs:

- **Available Repositories** provides repository search and a selectable list. Each entry can show its name, scope, fixture marker, active state, decision/entity/PR/commit counts, and an external repository link.
- **Custom Repository** provides fields for owner, repository name, branch, and optional scope. Submitting creates a repository target with zero initial counts, selects it, and closes the dialog.

The dialog can be dismissed using its close control or backdrop. Selecting an available repository also closes it.

### Decision detail drawer

The shared drawer opens from decision cards, citation receipts, and graph selections. It slides in from the right over the page and can be closed with its close control, backdrop, or Escape.

When detail data is available, it displays:

- Decision ID and state
- Summary and quoted rationale, or an explicit note when no quote was recorded
- Linked code entities and recorded authors
- Source artifact type, number, and link
- Supersession rule
- Recorded, effective, and ended dates when available
- Supersession lineage and links to related decisions
- Citations and their source details

The drawer supports copying a decision summary and distinguishes loading and error states.

## Responsive behavior and accessibility

- Navigation collapses to an overlay on narrow screens; selecting a page closes the overlay.
- The Investigate answer and evidence layout changes from side-by-side to stacked on narrow screens.
- Landing-page cards and dashboard grids reflow into fewer columns as available space decreases.
- Search results and long lists have bounded, scrollable regions where appropriate.
- The graph offers a list mode as an alternative to its visual canvas.
- Navigation, controls, search fields, status messages, and the file search use accessible labels or semantic status/error roles where implemented.
- The decision drawer supports Escape dismissal.

## Information flow

- The Overview, Investigate, Decisions, Before You Change, Knowledge Graph, and Repo Status pages all use the active repository.
- Investigate stores the latest question and answer as in-memory context for Decisions and Knowledge Graph.
- Decisions and Knowledge Graph use that context only when it belongs to the currently selected repository.
- Before You Change performs its own file search and loads repository decision history for the selected file.
- Repo Status reads health, dependency, and repository telemetry independently of investigation context.
- Route changes use browser history; repository selection and the sidebar open state persist in browser storage.
