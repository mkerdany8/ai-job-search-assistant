# Scoring Check

Two cases. A role I could plausibly get, and a role I clearly could not.

## Strong fit case: Software Engineer I, TD

Source: `postings-test/software-engineer-i-td.pdf`
Stored run: `data/applications/software-engineer-i-td.json`

Four runs on the identical PDF.

| Run | Required skills extracted | Skill coverage | Overall | Band |
| :-- | :-- | :-- | :-- | :-- |
| 1 | 17 | 24% | 40% | Stretch worth applying for |
| 2 | 7 | 29% | 39% | Stretch worth applying for |
| 3 | not logged | not logged | 40% | Stretch worth applying for |
| 4 | 6 | 33% | 38% | Stretch worth applying for |

Run 4 is the one saved in `data/applications/`. Its dimension scores:

| Dimension | Score |
| :-- | :-- |
| required_skills | 35 |
| preferred_skills | 15 |
| experience | 20 |
| education | 70 |
| market_alignment | 65 |

Run 4 matched Python and APIs. It missed relational data stores, NoSQL data
stores, cloud platforms and CI/CD pipelines. The posting asks for 2 years of
experience and I have none professionally, which is what pulled the experience
dimension down to 20.

## Weak fit case: Senior Manager Business Operations, RBC

Source: `postings-test/senior-manager-business-ops-rbc.pdf`
Stored run: `data/applications/senior-manager-business-operations-rbc.json`

| Run | Overall | Band |
| :-- | :-- | :-- |
| 1 | 19% | Growth target |
| 2 | 18% | Growth target |

Run 2 is the one saved. Its dimension scores:

| Dimension | Score |
| :-- | :-- |
| required_skills | 25 |
| preferred_skills | 30 |
| experience | 5 |
| education | 10 |
| market_alignment | 10 |

The posting asks for 8+ years and a Master's degree, preferably an MBA. The
experience and education dimensions are correctly near the floor.

Extraction on this posting was poor in a way worth recording. It returned
"Artificial Intelligence" and "AI" as two separate required skills, and split
MS Office into MS Office, Word, Excel and PowerPoint. So four of the six
required skills are one requirement, and two of them are the same requirement
written twice.

## Consistency check

The TD score moved between 38% and 40% across four runs. The band did not
move. All four runs landed in "stretch worth applying for".

The required skill count on those runs went from 17 down to 6. That is a 2.4x
swing in the denominator from the identical PDF, and the band held anyway.

I read that two ways. The fixed threshold table is doing its job, because the
band is what I actually act on and it stayed put. But the score surviving that
much input noise is partly luck. A posting sitting near 30% or 50% would flip
bands on the same amount of variation.

## My judgement

I trust the fit score least out of everything the system produces. The reason
is not the scoring logic. It is that extraction upstream is noisy and the
score inherits that noise. The skill overlap is computed exactly, but it is
computed from a list that changes run to run.

I agree with the TD stretch rating. I do not have Docker, CI/CD, or
professional experience. Calling that a stretch is honest. I would still apply,
and the report says to apply, so the rating and the advice line up with what I
would actually do.

I agree with the RBC growth rating. It is an 8+ year strategy role with a
Master's requirement and it has nothing to do with my background. An 18%
score is right.

The biggest thing I would change is that the fit score should account for how
specific a posting is, not just how much of it I match. Right now a vague
posting scores high because there is almost nothing to miss. A detailed
posting scores lower because there is more to miss, even when it is a better
match for me in practice. Those two should not be scored on the same scale. I
would want the score to carry some measure of how much the posting actually
committed to.

I would want a human checking this score before acting on it. In practice that
human is me, and what I check is the missing skills list rather than the
number.
