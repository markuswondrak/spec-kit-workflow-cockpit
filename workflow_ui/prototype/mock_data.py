"""Deliberately static fixtures. No engine, repository writes, or real execution."""

PROJECT_PATH = "/work/acme/search-service"
BRANCH = "feature/indexed-search"
BASE = "a19c2f1"
RUN_ID = "01J8ZQ7M4T2R9K"
CONTEXT_PATH = f".specify/workflows/runs/{RUN_ID}/cockpit-context.md"

WORKFLOWS = [
    dict(name="feature-delivery", gates=2,
         description="From a clear specification to a verified implementation.",
         nodes=["prepare", "analyze", "review_spec", "plan", "implement",
                "verify", "review_implementation", "finish"],
         gate="review_spec", next="plan", retry="analyze",
         question="Is the specification complete enough to plan?",
         input="Feature description", value="Add indexed search to the catalog"),
    dict(name="release-check", gates=1,
         description="Check the release. Inspect the evidence. Ship with confidence.",
         nodes=["prepare", "audit", "verify", "review_release", "publish"],
         gate="review_release", next="publish", retry="audit",
         question="Is this release candidate ready to publish?",
         input="Release version", value="v2.4.0"),
    dict(name="dependency-refresh", gates=0,
         description="Refresh locked dependencies and verify the result.",
         nodes=["scan", "update", "test", "finish"],
         gate=None, next="test", retry="update", question="",
         input="Dependency scope", value="Production dependencies"),
]

DECISIONS = [("1", "approve"), ("2", "retry"), ("3", "skip")]

FILES = [
    dict(status="M", path="README.md", added=5, removed=4,
         diff=[("hunk", "@@ -12,2 +12,3 @@ Search"),
               ("del", "- Search is not implemented yet."),
               ("add", "+ Search uses the catalog index."),
               ("add", "+ See specs/042-search/spec.md."),
               ("ctx", "  Run the application with make dev.")],
         content="# Search service\n\nSearch uses the catalog index.\n\n"
                 "See `specs/042-search/spec.md`.\n\nRun the application with `make dev`."),
    dict(status="M", path="specs/042-search/checklist.md", added=12, removed=8,
         diff=[("hunk", "@@ -1,4 +1,5 @@ Readiness"),
               ("del", "- [ ] Acceptance scenarios defined"),
               ("add", "+ [x] Acceptance scenarios defined"),
               ("ctx", "  [ ] Relevance ranking documented"),
               ("add", "+ [ ] Pagination behaviour defined")],
         content="# Readiness checklist\n\n- [x] Acceptance scenarios defined\n"
                 "- [ ] Relevance ranking documented\n- [ ] Pagination behaviour defined"),
    dict(status="+", path="specs/042-search/spec.md", added=96, removed=0,
         diff=[("hunk", "@@ -0,0 +1,96 @@ New specification"),
               ("add", "+ # Indexed search"), ("add", "+"),
               ("add", "+ Fast, ranked search for the catalog."),
               ("add", "+"), ("add", "+ ## Acceptance scenarios"),
               ("add", "+ Given a catalog with thousands of items"),
               ("add", "+ When a customer searches for a term"),
               ("add", "+ Then ranked results appear under 200 ms"),
               ("add", "+"), ("add", "+ ## Scope"),
               ("add", "+ - Catalog index and query parsing"),
               ("add", "+ - Relevance ranking and pagination")],
         content="# Indexed search\n\nFast, ranked search for the catalog.\n\n"
                 "## Acceptance scenarios\n\n"
                 "1. **Given** a catalog with thousands of items\n"
                 "2. **When** a customer searches for a term\n"
                 "3. **Then** ranked results appear in **under 200 ms**\n\n"
                 "## Scope\n\nCatalog index, query parsing, relevance ranking "
                 "and pagination.\n\n## Out of scope\n\n"
                 "Personalization and cross-catalog search."),
    dict(status="R", path="docs/search.md", previous="docs/search-notes.md",
         added=0, removed=0,
         diff=[("hunk", "similarity index 100%"),
               ("ctx", "rename from docs/search-notes.md"),
               ("ctx", "rename to docs/search.md")],
         content="# Search architecture\n\nThe catalog index is rebuilt "
                 "incrementally when products change."),
    dict(status="-", path="notes/draft.md", added=0, removed=41,
         diff=[("hunk", "@@ -1,41 +0,0 @@ Deleted draft"),
               ("del", "- # Search notes"),
               ("del", "- Explore a catalog index."),
               ("del", "- Superseded by specs/042-search/spec.md.")],
         content="# Search notes\n\nExplore a catalog index.\n\n"
                 "Superseded by `specs/042-search/spec.md`."),
]

CHANGE_SUMMARY = "5 files  +113 -53"


def node_states(workflow: dict, scene: str, attempt: int = 1, active: str | None = None) -> list[tuple]:
    nodes = workflow["nodes"]
    if scene == "gate":
        current = workflow["gate"]
    elif scene == "failed":
        current = "verify" if "verify" in nodes else "test"
    elif active:
        current = active
    elif attempt > 1:
        current = workflow["retry"]
    else:
        current = "implement" if "implement" in nodes else nodes[1]
    index = nodes.index(current) if current in nodes else len(nodes) - 1
    result = []
    for i, name in enumerate(nodes):
        state = "done" if i < index else "pending"
        if i == index:
            state = {"gate": "gate", "failed": "failed", "aborted": "aborted"}.get(scene, "running")
        if scene == "complete":
            state = "done"
        meta = "00:04" if i == 0 else "00:31" if state == "done" else ""
        if i == index and scene != "complete":
            meta = "gate" if scene == "gate" else "00:47"
        result.append((name, state, meta))
    return result


def engine_lines(workflow: dict, scene: str, attempt: int = 1, active: str | None = None) -> list[str]:
    lines = [f"$ specify workflow run {workflow['name']} ...",
             "prepare: project context resolved",
             "analyze: 3 acceptance scenarios found"]
    if scene == "gate":
        lines += [f"{workflow['gate']}: waiting for verdict_input",
                  f"  {workflow['question']}", "  choose: approve | retry | skip"]
    elif scene == "failed":
        lines += ["verify: running test suite", "FAIL search.test_latency",
                  "AssertionError: 284 ms exceeds 200 ms", "verify: exited with status 1"]
    elif scene == "complete":
        lines += ["verify: all checks passed", "finish: workflow completed successfully"]
    elif scene == "aborted":
        lines += ["abort: requested by user", "engine: stopped; worktree changes preserved"]
    else:
        current = next(n for n, s, _ in node_states(workflow, scene, attempt, active) if s == "running")
        lines += [f"{current}: attempt {attempt}", f"{current}: processing catalog search",
                  f"{current}: writing worktree changes"]
    return lines
