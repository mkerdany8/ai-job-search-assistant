# Failure Analysis

Five failures I found by testing. Four are fixed. One is not.

## 1. The fit scorer rated a confirmed scam 94%

### What happened

The fake NorthBridge posting was correctly flagged red with six negative
signals. The fit assessment directly below that scored it 94% and labelled it
"Strong match. Apply. You meet the bar for this role." Sections 3 to 5 then
drafted a positioning angle, a cover letter opening addressed to the scammers,
and questions to ask them about their mentorship practices.

Section 1 said "Do NOT apply to this posting." Section 2 said "Apply." Two
lines apart.

### Why it happened

The posting scored high because it is vague. Its only stated requirement was
"basic computer skills", so required_skills came back near full marks and
experience came back at 100. The score measures how much of the posting I
match. A posting that asks for almost nothing is matched almost completely.

That inverts the signal. The vaguer the fraud, the better it scores. And
vagueness is deliberate in these postings, because the scammer wants the
widest possible pool of replies.

The deeper cause is that fit scoring and legitimacy did not know about each
other. Each was correct on its own. Nothing joined them up.

### What I would change, and what changed

The verdict now feeds the fit scorer and the advice generator. On a red
verdict the band label becomes "Not an application target", the call to action
is removed, and a high score is explained as a fraud signal rather than a
recommendation. Sections 3 to 5 switch to analysis of what that kind of role
involves, with no letter, no company references and no questions to ask.

The score itself is unchanged and still shown. It is an honest measure of
requirement overlap. It just is not a reason to do anything.

The rerun scored 98% and reads "Not an application target". Every use of the
word "apply" in the rerun report is part of an instruction not to.

## 2. Extraction granularity varies run to run

### What happened

The same TD PDF produced 17 required skills on one run and 7 on the next. A
later run produced 6. One bullet reading "solid software engineering
fundamentals, including coding, debugging, unit testing, source control"
became five separate required skills on the 17 entry run.

Scores across four runs were 40, 39, 40 and 38.

### Why it happened

Two causes stacked. The schema field description asked for individual items
with no combined phrases, which pushed the model to break prose into pieces.
And the model is not deterministic on where it draws the line between a skill
and a description of the job, so the same instruction produces different
granularity each run.

Every generic entry is one more thing to miss, so a noisy denominator drags
the score down and moves it around.

### What I would change, and what changed

Generic entries are now filtered in `src/fit.py` before coverage is computed.
Named technologies and named practices like CI/CD and REST APIs are kept.
Words like coding, debugging and unit testing are dropped. Everything filtered
is logged and shown in the report.

The filtering happens in scoring only. Extraction still records what the
posting asked for, so `data/jobs/` stays a faithful record and the market
analysis is not invalidated.

This reduces the damage but does not fix the cause. Extraction still varies.
If I were doing this again I would extract skills more than once and keep only
the entries that appear in every pass.

## 3. The market report dropped the salary sample size

### What happened

`data/analysis/market-analysis.json` says:

> 5 out of 8 postings listed salary data. Salaries range from CA$61,600 to
> CA$130,200.

`reports/market-analysis.md`, generated from that JSON, says:

> Of the postings providing financial data, the salary range is CA$61,600 to
> CA$130,200.

The count is gone. A reader of the Markdown cannot tell whether the range
comes from 5 postings or 2.

### Why it happened

The report writer is a separate LLM call that turns the structured analysis
into prose. Nothing in that step requires it to keep the numbers. It was told
to be readable and it dropped a detail to read more smoothly.

### What I would change

The numbers in the structured analysis are the whole point of computing them.
The report step should be checked against the JSON rather than trusted, or the
sample size should be written into the template rather than left to the model.
I would rather have the count present and the sentence clumsy.

## 4. The salary range mixes hourly and annual pay

### What happened

The reported market range is CA$61,600 to CA$130,200. Those two endpoints are
the BMO minimum and the IBM maximum, both annual salaries.

The Siemens posting lists $35 to $40 per hour, which is a co-op rate. It is
one of the 5 of 8 postings counted as listing salary data. It cannot be
compared to an annual figure without converting it, and it is not converted.

Nothing in `reports/market-analysis.md` mentions hourly pay or co-op rates at
all. The word hourly does not appear in the report.

### Why it happened

The `SalaryRange` schema has a `period` field, so the data is there. The
aggregation step does not group by period or convert between periods before
summarising. It was given five salary figures and reported the smallest and
largest.

The result is a range presented as if all five postings were comparable when
one of them is on a different scale, and a co-op rate that silently vanishes
from a report that still counts it.

### What I would change

Normalise to one period before aggregating, or report hourly and annual
separately. Roughly, $35 to $40 per hour is about $73,000 to $83,000 a year at
full time hours, which sits inside the reported range rather than below it. So
the range is not wrong by much. It is just not something the report earned the
right to say.

## 5. A failed legitimacy check fell through to the green path

### What happened

When the legitimacy check cannot complete, it returns a yellow verdict with
`assessment_succeeded` set to false. I mapped that state to "unknown" so a
failed check would not be treated as evidence of fraud. That part was right.

Unknown then fell through to the green branch, and the fit assessment printed
an unqualified "Apply." for a posting nobody had verified.

### Why it happened

I wrote the branch as red, then yellow, then everything else. Unknown was not
red and was not yellow, so it landed in the default case, which was written
for green. It was a gap in the conditions rather than a decision.

### What I would change, and what changed

Unknown now takes the same caution as yellow. The message adds a line about
confirming the posting on the employer's own careers page before sending
anything.

The general lesson is that a check which did not run is not a check that
passed. Any state that means "we do not know" should default to the cautious
branch, not the confident one.

## My judgement

I trust the legitimacy agent most. It caught every red flag I planted and it
checked a second domain on its own without being told to.

I trust the fit score least. The scoring logic is fine, but extraction is noisy
and the score inherits that. Four runs on the same PDF gave four different skill
counts.

I would want a human checking the fit score and the resume edits before acting
on them. The resume edits go out under my name, so I need to be able to defend
every claim in an interview.

The legitimacy verdict I would trust as a first pass, but I would still check
the company myself before sending any personal information.

The main thing I would change is that the fit score should account for how
specific a posting is, not just how much of it I match. Almost every failure
here comes back to the same thing. The system measures what the posting says
and treats that as a measurement of the job. When the posting is vague or
written in prose, the measurement gets worse and nothing downstream notices.
