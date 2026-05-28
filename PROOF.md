# GeminiAnalyzer — Proof

_Plain-language record for anyone who needs to understand this without being a coder._
_Last reviewed: 2026-05-28._

## 1. What this thing is

A small desktop program that opens the file you get when you download your
Google chat history with Gemini, and shows it in a way you can actually use.

## 2. What it does for you

- Sorts your old chats into clear groups by topic, like "Coding," "Money,"
  "Writing," and "Games."
- Finds the apps and projects you were building and **glues the scattered
  pieces back together** into one place, in order.
- Pulls every bit of code you ever wrote with Gemini out into one click-to-copy
  list, so you can paste it into another tool.
- Makes a pretty timeline so you can see what months you were busy and what
  you were busy with.
- Spots the duplicate chats in your download and gives you a list of them
  (it does **not** delete anything — it just tells you what's repeated).
- When you ask, can write a short summary of any project or a deeper review,
  using a cloud helper.
- Saves a clean "project file" you can drop into another AI helper to keep
  working on the project there.

## 3. How it was made

The user designed it. An AI assistant helped build it from those
specifications.

The program is written in Python (a common programming language). The window
you click on is built with a standard tool called tkinter that already comes
with Python — no extra software to install. The optional cloud summary
feature talks to OpenRouter, which is a service that lets you use many
different AI models with one account.

## 4. What it costs / what it gives back

- **Money:** the program itself is free. The optional cloud summary uses
  free-tier models, which means no charge per use, but the company providing
  the model is allowed to look at your text and possibly use it to train their
  own AI. You decide each time whether to click that button.
- **Time:** opens a 46 MB Gemini download in under 8 seconds. Each summary or
  review takes a few seconds the first time and is then saved so it's instant
  on later clicks.
- **Data:** everything stays on your computer unless you specifically click
  the Summarize or Deep Review button on a project. The duplicate finder,
  sorter, and project file maker never touch the internet.
- **Control:** the program never deletes or changes your original Google
  download — it only reads it. The duplicate finder writes a list of
  duplicates to a file you choose; whether to clean anything up is up to you.

## 5. Who is responsible

The user, as the designer of record. Last reviewed by them on 2026-05-28.

## 6. What proof exists that it works

- The program reads a real 46-megabyte, 8,653-conversation download from the
  designer's own Google Takeout in 7.4 seconds, sorts every conversation in
  another 5.8 seconds, and stitches 154 real projects back together in 1.3
  seconds. (See `Desktop/AI/docs/2026-05-28_gemini_analyzer.md` Phase 1 and 2
  receipts.)
- All 28 automated tests pass in under one second. They check that the parts
  most likely to break quietly (sorting into the right group, gluing
  fragments together, not modifying the source, refusing to talk to the
  cloud if no key is set) still behave correctly. Run with
  `python -m pytest tests/ -q`.
- A standalone Windows program is built and lives at
  `Desktop/My Apps/GeminiAnalyzer.exe`. It's 12 megabytes and was rebuilt on
  2026-05-28.
- Before each phase was called "done," an independent scan looked for ways
  the code could fail silently. It found 19 issues total across the upgrade,
  including one regression introduced mid-build. Every one was fixed and
  re-verified before the next phase started.

## 7. Changelog

- **On 2026-05-28**, upgraded the program to a "version 2." It now sorts
  conversations into more topic groups (added Writing & Editing, Planning,
  Money, Pictures & Design, Hardware, Games — 13 in total). It finds the
  pieces of a project that Google scattered across many chats and shows them
  back together in time order, with a timeline view. It can optionally send a
  project to a free cloud AI and get back a summary or a deeper review, which
  are saved so the same chat is never sent twice. It can build a "Claude-
  ready" project file you can paste into another AI helper. It finds
  duplicate chats and writes a report without changing anything. A real
  Windows program was built and copied to the My Apps folder. The cost,
  data, and control story above is up to date.
- **Earlier** — first version sorted conversations into 7 topic groups and
  pulled out the code blocks; the new version keeps all of that working and
  adds the items above.
