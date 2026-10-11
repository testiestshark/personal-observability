# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the right-hand column to match whatever vocabulary you actually use.

## Parent issues

Beyond the five triage roles, this repo has a `parent` label. Put it on **any issue that
has other issues coming off it**: follow-ups, split-out tickets, sub-issues. It sits
alongside the triage label (a parent can be `ready-for-agent` and `parent`), and it is
added when the first child issue is opened, not when the parent is created.

Each child says `Follow-up to #<parent>` (or `Part of #<parent>`) at the top of its body,
so the link is readable without opening the parent.

## Paused issues

There is also a `paused` label, for an issue that is **deliberately on hold until a stated
date or event**: a check that needs a fresh run of something, work that waits on an
external change. It is none of the triage roles. It is not waiting on a decision
(`needs-triage`) or on the reporter (`needs-info`), and it is not ready to build
(`ready-for-agent`), so an agent leaves it alone until what it waits for has happened.

- Say what it waits for, and by when, in the title and at the top of the body: for
  example "paused until 2026-10-15", directly under the `Follow-up to #<parent>` line.
- Do not also apply `ready-for-agent`. When the date or event has passed, take `paused`
  off and either do the work or close the issue.

Example: the check that the scheduled Garmin sync stores splits for a brand-new run
(#117), which can only be seen after the next real run.
