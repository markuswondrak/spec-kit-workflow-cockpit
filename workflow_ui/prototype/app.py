"""Flight Recorder: an interactive, fixture-only Textual design prototype."""

from __future__ import annotations

import argparse

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, RichLog, Static
from textual.widgets.option_list import Option

import mock_data as data
from components import (AdaptiveScreen, ConfirmScreen, HelpScreen, NavList,
                        COLD, FAULT, FOG, HOLD, PAPER, SIGNAL, STATUS, text, truncate)
from review import ReviewPane


class CockpitScreen(AdaptiveScreen):
    BINDINGS = [
        Binding("s", "mode('state')", "Overview"),
        Binding("g", "mode('gate')", "Gate"),
        Binding("c", "mode('changes')", "Changes"),
        Binding("l", "output", "Output"), Binding("e", "collapse", "Collapse output"),
        Binding("end", "tail", show=False),
        Binding("d", "content('diff')", show=False),
        Binding("r", "content('rendered')", show=False),
        Binding("slash", "filter", show=False),
        Binding("1", "decide('approve')", show=False),
        Binding("2", "decide('retry')", show=False),
        Binding("3", "decide('skip')", show=False),
        Binding("x,q", "quit", "Abort"), Binding("question_mark", "help", "Help"),
        Binding("f2", "scene('running')", show=False),
        Binding("f3", "scene('gate')", show=False),
        Binding("f4", "scene('complete')", show=False),
        Binding("f5", "scene('failed')", show=False),
    ]

    def __init__(self, workflow: dict | None = None, scene: str = "gate") -> None:
        super().__init__()
        self.workflow = workflow or data.WORKFLOWS[0]
        self.scene = scene if scene != "gate" or self.workflow["gates"] else "running"
        self.mode = "gate" if self.scene == "gate" else "state"
        self.attempt = 1
        self.expanded = self.scene == "failed"
        self.selected_node = None
        self.active_node = None

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            with Horizontal(id="masthead"):
                yield Static(text((" C / ", f"bold {HOLD}"), ("WORKFLOW COCKPIT", f"bold {PAPER}")), id="wordmark")
                yield Static(id="run-status")
                yield Static("?  help", id="help-hint")
            yield Static(id="identity")
            with Horizontal(id="workspace"):
                with Vertical(id="runway"):
                    yield Static("01 / WORKFLOW", classes="section-label")
                    yield Static(id="workflow-name")
                    yield Static(id="run-progress")
                    yield NavList(id="nodes")
                    yield Static(text(("CONTROL FLOW\n", FOG),
                                      ("has_spec -> review\n", PAPER),
                                      ("retry    -> analyze", HOLD)), id="flow-note")
                    yield Static("enter  inspect step", id="runway-note")
                with Vertical(id="focus"):
                    with Horizontal(id="view-tabs"):
                        yield Button("s  Overview", id="tab-state", classes="view-tab")
                        yield Button("c  Changes", id="tab-changes", classes="view-tab")
                        yield Button("g  Gate review", id="tab-gate", classes="view-tab")
                    with VerticalScroll(id="brief"):
                        yield Static(id="brief-kicker")
                        yield Static(id="brief-title")
                        yield Static(id="brief-copy")
                    with VerticalScroll(id="overview"):
                        yield Static(id="overview-content")
                        yield Button("Inspect worktree changes  [c]", id="inspect", classes="secondary-action")
                    yield ReviewPane(id="review")
                    yield Static(text(("CONTEXT  ", FOG), (data.CONTEXT_PATH, COLD)), id="context")
                    with Horizontal(id="decision-bar"):
                        yield Static("DECIDE", id="decision-label")
                        for key, choice in data.DECISIONS:
                            yield Button(f"{key}  {choice}", id=f"choice-{choice}", classes="decision")
                        yield Static("Confirmation\nrequired", id="decision-hint")
                    with Vertical(id="output-panel"):
                        with Horizontal(id="output-heading"):
                            yield Static(id="output-title")
                            yield Button("l  expand", id="output-toggle")
                        yield RichLog(id="engine", highlight=False, markup=False, wrap=True, max_lines=500)
            with Horizontal(id="command-rail"):
                yield Static(id="commands")
                yield Button("x  Abort run", id="abort")
            yield Static("PREVIEW / NO ENGINE   F2 running   F3 gate   F4 complete   F5 failed", id="preview-rail")
        yield Static(id="resize-guard")

    def on_mount(self) -> None:
        self.apply_scene()
        self.apply_size(self.size.width, self.size.height)

    def apply_scene(self) -> None:
        self.selected_node = None
        wf = self.workflow
        self.nodes = data.node_states(wf, self.scene, self.attempt, self.active_node)
        labels = {"gate": ("[!] WAITING FOR YOU", HOLD), "running": ("[>] RUNNING", SIGNAL),
                  "complete": ("[x] COMPLETE", SIGNAL), "failed": ("[X] FAILED", FAULT),
                  "aborted": ("[/] ABORTED", FAULT)}
        label, color = labels[self.scene]
        self.query_one("#run-status", Static).update(text((label, f"bold {color}")))
        elapsed = "06:42" if self.scene == "complete" else "00:35" if self.scene == "gate" else "04:12"
        self.query_one("#identity", Static).update(text(
            ("  " + data.BRANCH, PAPER), ("   /   BASE ", FOG), (data.BASE, PAPER),
            ("   /   ", FOG), (elapsed, PAPER), ("   /   RUN " + data.RUN_ID, FOG)))
        self.query_one("#workflow-name", Static).update(wf["name"])
        done = sum(state == "done" for _, state, _ in self.nodes)
        self.query_one("#run-progress", Static).update(text(
            ("=" * done, SIGNAL), ("-" * (len(self.nodes) - done), FOG),
            (f" | {done}/{len(self.nodes)} complete", FOG)))
        options = []
        for i, (name, state, meta) in enumerate(self.nodes):
            symbol, tone = STATUS[state]
            connector = "|" if i < len(self.nodes) - 1 else " "
            detail = "gate" if state == "gate" else meta or "pending"
            if name == "analyze" and wf["name"] == "feature-delivery":
                detail += " / has_spec"
            options.append(Option(text((f"{symbol} ", tone),
                                       (truncate(name, 21), PAPER if state != "pending" else FOG),
                                       (f"\n {connector}  {detail}", tone if state == "gate" else FOG)), id=name))
        listing = self.query_one("#nodes", NavList)
        listing.clear_options().add_options(options)
        current = next((i for i, (_, s, _) in enumerate(self.nodes) if s in ("running", "gate", "failed", "aborted")), len(self.nodes) - 1)
        listing.highlighted = current
        self.query_one("#flow-note").set_class(wf["name"] != "feature-delivery", "not-applicable")
        self.query_one("#tab-gate").display = self.scene == "gate"
        self.query_one("#review", ReviewPane).paused = self.scene == "gate"
        log = self.query_one("#engine", RichLog)
        log.clear()
        for line in data.engine_lines(wf, self.scene, self.attempt, self.active_node):
            log.write(text((line, FAULT if "FAIL" in line or "Error" in line else FOG)))
        self.apply_mode()
        self.apply_output()

    def apply_mode(self) -> None:
        at_gate = self.scene == "gate"
        review = self.mode in ("gate", "changes")
        self.query_one("#review").display = review
        self.query_one("#overview").display = not review
        self.query_one("#decision-bar").display = at_gate and self.mode == "gate"
        for name in ("state", "changes", "gate"):
            self.query_one(f"#tab-{name}").set_class(self.mode == name, "active-tab")
        if self.mode == "gate":
            kicker = "02 / REVIEW SPECIFICATION" if self.workflow["gate"] == "review_spec" else "02 / GATE REVIEW"
            title, copy, color = self.workflow["question"], f"{self.workflow['gate']}  /  attempt {self.attempt}  /  engine paused", HOLD
        elif self.mode == "changes":
            kicker, title, copy, color = "02 / WORKTREE CHANGES", "The evidence, in full context.", f"Compared with {data.BASE}. Includes changes present before the run.", PAPER
        elif self.scene == "complete":
            kicker, title, copy, color = "02 / RUN COMPLETE", "Verified. Ready for your next move.", "The workflow is complete. Your worktree changes remain available to review.", SIGNAL
        elif self.scene == "failed":
            kicker, title, copy, color = "02 / RUN FAILED", "Verification needs attention.", "verify / attempt 1 / test command exited with status 1", FAULT
        elif self.scene == "aborted":
            kicker, title, copy, color = "02 / RUN ABORTED", "Stopped. Your changes are safe.", "Aborted by you. The engine is no longer running.", FAULT
        else:
            node = self.selected_node or next((n for n, s, _ in self.nodes if s in ("running", "gate")), self.nodes[-1][0])
            kicker, title = "02 / STEP OVERVIEW", node
            copy, color = f"{self.workflow['name']}  /  attempt {self.attempt}  /  {'paused at gate' if at_gate else 'automated execution'}", HOLD if at_gate else SIGNAL
        self.query_one("#brief-kicker", Static).update(text((kicker, color)))
        self.query_one("#brief-title", Static).update(text((title, f"bold {PAPER}")))
        self.query_one("#brief-copy", Static).update(text((copy, FOG)))
        self.query_one("#brief").set_class(at_gate and self.mode == "gate", "gate-brief")
        current = self.selected_node or next((n for n, s, _ in self.nodes if s != "done"), self.nodes[-1][0])
        index = self.workflow["nodes"].index(current)
        next_nodes = " -> ".join(self.workflow["nodes"][index + 1:index + 3]) or "End of workflow"
        status = next(s for n, s, _ in self.nodes if n == current)
        if self.scene == "complete":
            body = text(("EXECUTION SUMMARY\n\n", FOG),
                        (f"{len(self.nodes)} steps completed   /   {self.workflow['gates']} gates   /   06:42 elapsed\n\n", PAPER),
                        ("WORKTREE CHANGES\n", FOG), (data.CHANGE_SUMMARY + "\n\n", SIGNAL),
                        ("No automatic commit. Review the result before you leave.", PAPER))
        elif self.scene == "failed":
            body = text(("FAILURE DETAIL\n\n", FOG), ("search.test_latency\n", PAPER),
                        ("284 ms exceeds the 200 ms acceptance threshold.\n\n", FAULT),
                        ("Output is expanded below. This session cannot resume.\nStart a new session after addressing the failure.", FOG))
        elif self.scene == "aborted":
            body = text(("ABORT SOURCE  user\n\n", FOG), (data.CHANGE_SUMMARY + "\n\n", PAPER),
                        ("Review the worktree or close this session.", FOG))
        else:
            body = text(("STEP INTENT\n\n", FOG),
                        (f"{current}  /  {status}\n", PAPER),
                        ("Creates the implementation described by the approved plan.\n\n" if current == "implement" else "Inspect this step in the context of the declared workflow.\n\n", PAPER),
                        ("UP NEXT\n", FOG), (next_nodes + "\n\n", COLD),
                        ("WORKTREE CHANGES\n", FOG), (data.CHANGE_SUMMARY, PAPER))
        self.query_one("#overview-content", Static).update(body)
        self.query_one("#commands", Static).update(text(
            (" Tab", COLD), (" focus   ", FOG), ("j/k", COLD), (" navigate   ", FOG),
            ("d/r  /", COLD), (" review   ", FOG), ("?", COLD), (" help", FOG)) if review else
            text((" c", COLD), (" review changes   ", FOG), ("l", COLD), (" output   ", FOG), ("?", COLD), (" help", FOG)))
        self.query_one("#abort", Button).label = "q  Close session" if self.terminal else "x  Abort run"

    @property
    def terminal(self) -> bool:
        return self.scene in ("complete", "failed", "aborted")

    def action_mode(self, mode: str) -> None:
        if mode == "gate" and self.scene != "gate":
            return
        self.mode = mode
        self.apply_mode()

    def action_scene(self, scene: str) -> None:
        if scene == "gate" and not self.workflow["gates"]:
            self.notify("This workflow has no gates.")
            return
        self.scene, self.attempt = scene, 1
        self.active_node = None
        self.mode = "gate" if scene == "gate" else "state"
        self.expanded = scene == "failed"
        self.apply_scene()

    def on_option_list_option_selected(self, event: NavList.OptionSelected) -> None:
        if event.option_list.id == "nodes":
            self.selected_node = str(event.option.id)
            self.action_mode("state")

    def apply_output(self) -> None:
        self.query_one("#output-panel").set_class(self.expanded, "expanded")
        state = "PAUSED" if self.scene == "gate" else "LIVE [>]" if self.scene == "running" else "STOPPED"
        self.query_one("#output-title", Static).update(text(("03 / ENGINE OUTPUT", FOG), (f" / {state}", HOLD if self.scene == "gate" else SIGNAL if self.scene == "running" else FOG)))
        self.query_one("#output-toggle", Button).label = "e  collapse" if self.expanded else "l  expand"

    def action_output(self) -> None:
        self.expanded = True
        self.apply_output()
        self.action_tail()

    def action_tail(self) -> None:
        self.query_one("#engine", RichLog).scroll_end(animate=False)

    def action_collapse(self) -> None:
        self.expanded = False
        self.apply_output()

    def action_decide(self, choice: str) -> None:
        if self.scene != "gate":
            return
        target = self.workflow["next"] if choice == "approve" else self.workflow["retry"] if choice == "retry" else self.workflow["nodes"][-1]
        self.app.push_screen(ConfirmScreen(choice, f"The workflow will continue to: {target}"),
                             lambda confirmed: self.after_decision(choice, confirmed))

    def after_decision(self, choice: str, confirmed: bool | None) -> None:
        if not confirmed:
            return
        self.scene, self.mode = "running", "state"
        self.attempt = 2 if choice == "retry" else 1
        self.active_node = self.workflow["next"] if choice == "approve" else self.workflow["retry"] if choice == "retry" else self.workflow["nodes"][-1]
        self.apply_scene()
        self.notify(f'Preview: "{choice}" confirmed. Running fixture loaded.', timeout=3)

    def action_quit(self) -> None:
        if self.terminal:
            self.app.exit()
        else:
            self.app.push_screen(ConfirmScreen("abort", "The engine will stop. This run cannot resume in this session.", True), self.after_abort)

    def after_abort(self, confirmed: bool | None) -> None:
        if confirmed:
            self.scene, self.mode = "aborted", "state"
            self.apply_scene()

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_content(self, mode: str) -> None:
        if self.mode in ("gate", "changes"):
            self.query_one("#review", ReviewPane).action_content(mode)

    def action_filter(self) -> None:
        if self.mode in ("gate", "changes"):
            self.query_one("#review", ReviewPane).action_filter()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        key = event.button.id or ""
        if key.startswith("tab-"):
            self.action_mode(key[4:])
        elif key.startswith("choice-"):
            self.action_decide(key[7:])
        elif key == "inspect":
            self.action_mode("changes")
        elif key == "output-toggle":
            self.action_collapse() if self.expanded else self.action_output()
        elif key == "abort":
            self.action_quit()


class CockpitApp(App):
    CSS_PATH = "styles.tcss"
    ENABLE_COMMAND_PALETTE = False
    TITLE = "Workflow Cockpit / Design Preview"

    def __init__(self, scene: str = "launch") -> None:
        super().__init__()
        self.initial_scene = scene

    def on_mount(self) -> None:
        from launch import LaunchScreen
        self.push_screen(LaunchScreen() if self.initial_scene == "launch" else CockpitScreen(scene=self.initial_scene))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", choices=["launch", "gate", "running", "complete", "failed"], default="launch")
    CockpitApp(parser.parse_args().scene).run()
