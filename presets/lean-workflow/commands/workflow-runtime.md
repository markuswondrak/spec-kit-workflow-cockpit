## Workflow Runtime

You are running **unattended inside an automated Spec Kit workflow**. No human is watching this
session and no one can respond or grant approvals. Therefore:

- **Never ask questions.** Do not use the `question` tool, do not ask for clarification, and do not
  wait for confirmation. Make informed defaults instead and record your assumptions in the artifact.
- **Never request permissions.** Assume the actions required by this command are authorized; do not
  pause for approval.
- **Never block.** If you are genuinely unable to proceed, stop and report the blocker in your final
  output so the workflow can surface it.
