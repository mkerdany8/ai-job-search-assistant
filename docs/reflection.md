# Reflection

Mostafa Elkerdany, AIP444 Assignment 2.

## 1. Did I structure the phases as workflows, agents, or a hybrid? What influenced the decision?

Hybrid. The pipelines are deterministic, and I only used agentic loops where
the work is actually open ended, which is company research and legitimacy
investigation. Everything else runs in a known order, so an agent there would
just add cost and randomness for nothing.

## 2. Which prompt engineering choices most improved extraction consistency across varied job postings?

Literal types for the enums, so the model cannot invent a value. Every field
required, with the optional ones explicitly nullable. Field descriptions doing
the prompt work instead of the system prompt. The biggest one was computing the
skill counts in Python and handing them to the model as ground truth instead of
asking it to count.

## 3. How did I design the legitimacy agent? What signals did I prioritise and why? What limitations does it have?

Registration date is weighted highest, but a red verdict needs more than that,
because a real young startup looks the same as a scam on that signal alone.
Privacy redaction counts as neutral since most registrars do it now. A contact
domain that does not match the company is the strongest single fraud signal.

Limits: it only sees the posting text and whatever search returns, it decides
what to look into fresh on every run, and an aged domain would get a fraud past
it.

## 4. What models did I use and how did cost influence the choice?

`google/gemini-3.1-flash-lite` for extraction, since that is schema filling and
a cheap fast model handles it. `google/gemini-3.5-flash` for legitimacy verdicts
and fit scoring, since those weigh conflicting evidence.

Cost did not really drive it. What mattered was getting output I could rely on.
The split came from matching the model to how hard the task was, and the cheaper
one happened to suit the easier task. Spend stayed inside my credits so it was
never the constraint.

## 5. Coding agent process for Phase 3

Agent: Claude Code, running Claude Opus 5.

Initial instructions: read `CLAUDE.md`, all of `src/` and both CLI scripts, then
plan before writing anything. Reuse the existing modules, follow the two stage
tool pattern from `research.py`, hard step limits on every loop.

Iterations: four. Plan, build, extraction granularity fix, red verdict fix.

Defects. It found and fixed four itself before handover. The whois parser
reported a nonexistent `.com` as registered since 1985, because the macOS whois
client returns the IANA record for the TLD and 1985 is when `.com` was created.
The skill matcher scored "RESTful APIs" as missing against a resume listing
"REST APIs". rdap.org returned 403 to the default requests user agent, so every
lookup was quietly falling back to whois. And a failed legitimacy check fell
through to the green path and printed "Apply." for a posting it had not
verified. I found the fifth myself by testing the fake posting. The fit scorer
rated a confirmed scam 94% and wrote a cover letter to the scammers.

What it got right and wrong about my codebase. It followed my conventions
without me repeating them, including the two stage tool pattern, stderr logging,
and the trick from `market.py` of computing counts in Python and handing them to
the model. It was wrong about my posting PDFs. It assumed they would contain
contact domains, but browser printed job board pages usually have none.

## 6. What other AI tools did I use?

### Tool 1: Claude Opus 5 (chat)

Where it helped: I used it to plan the project and work through Phases 1 and 2
step by step. It designed the Pydantic schemas and the two stage pattern of
running tools with create() then getting structured output with parse(). I also
ran it alongside Claude Code, feeding it the agent's output so it could check
the work and keep track of what had been committed.

Where I had to correct or reject its output: it gave me a model slug that had
been retired, so my first extraction run failed with a 404 three times before
erroring out. The retry loop it had written for me treated that 404 as
retryable, which was a second bug in its own code. I had to look up the current
slug and patch the retry logic to fail fast on 4xx.

### Tool 2: Claude Code (Opus 5)

Where it helped: it built Phase 3 and caught things I would have missed. Before
I ran anything, it warned me that changing the extraction prompt would not
trigger re-extraction, because the skip logic hashes the source PDF and not the
prompt. It also pushed back on a claim I had brought in about the salary range
blending hourly and annual figures, checked the data, and showed me the defect
was real but differently shaped.

Where I had to correct or reject its output: on the fake posting I wrote to test
the legitimacy agent, its first fix was heavier than I wanted. I had to tell it
twice to leave my judgement sections alone rather than writing opinions in my
voice.
