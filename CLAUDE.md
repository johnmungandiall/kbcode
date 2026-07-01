# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`kbcode` is a small, self-contained AI coding agent that runs in the terminal. It is itself built by blending ideas from five reference agents (cloned, for study only, into the gitignored `references/`): Claude Code (agentic loop + tools), Hermes (persistent memory/skills + context compaction), claude-kb (token-cheap `kb/` notes + `path:line` pointer checking), Kilo Code (modes), and openclaw (tool-call repair). When extending kbcode, the working assumption is that new capability comes from one of those concepts.

## Knowledge Base (read FIRST — saves tokens)
This repo keeps a compact KB in `kb/`. The FULL KB rules (how to maintain it,
sub-agents, user-map) live in `kb/about-kb.md` — read it before you maintain the
KB, edit notes, or dispatch a sub-agent.

- READ FIRST: before ANY task (answer, code, debug, plan), open the relevant
  `kb/` notes to orient — do NOT grep or scan the whole repo first. If the KB
  lacks something, follow its `path:line` pointers into the code, then fold the
  finding back in.
- AFTER CHANGING code/config: update the affected `kb/` note(s) in the SAME
  session, before ending your turn — part of "done". (Exact rules: `kb/about-kb.md`.)
- WHEN THE USER states/corrects a durable preference, goal, or rule: update
  `kb/about-you.md` the same session.
- SUB-AGENTS & SKILLS: anything you dispatch starts cold — pass it these rules.
- NO DRIFT: changed a value/name/contract that lives in MORE THAN ONE place? update
  every copy and search the old value to zero. A trap noted in a feature note also
  gets a stub in `kb/gotchas.md`; a multi-step procedure gets a `kb/runbooks/` note.
  End a code/config change with a "KB: updated <note>" / "no change needed" line.

Map of the KB:
- kb/overview.md — entry points, how to run, version, "last indexed" marker
- kb/about-kb.md — full KB-maintenance + sub-agent + user-map rules (read before maintaining)
- kb/architecture.md — component map, control flow, the normalized-message invariant, links into kb/features/
- kb/about-you.md — what the USER prefers: working style, tech, goals, rules
- kb/features/ — deep-dives: providers, vision, modes-subagents, sessions, config, context-management, tools-and-repair, safety
- kb/conventions.md, kb/glossary.md — code/note style rules; project-specific terms
- kb/gotchas.md, kb/changelog.md, kb/cheatsheet.md — traps, KB/release history, command cheatsheet

## Boundaries

- `references/` is cloned third-party source for studying concepts — **gitignored, not part of the product**. Never import from it or ship its code.
- `.kbcode/` (memory db, settings) and `.env` are gitignored, per-machine/secret. The README and `.env.example` document every provider and tuning env var.
