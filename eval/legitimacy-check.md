# Legitimacy Check

Two cases. A real posting from a real bank, and a fake posting I wrote with
planted fraud signals.

## Legitimate case: Software Engineer I, TD

Source: `postings-test/software-engineer-i-td.pdf`
Stored run: `data/applications/software-engineer-i-td.json`

Verdict: green. Four signals, all positive, none negative.

| Signal | Weight | Evidence |
| :-- | :-- | :-- |
| Highly established corporate domain | strong | td.com registered 1998-04-15, expires 2028-04-14 |
| Independently verifiable job details | strong | Search for the team "EDMO Data Catalog services" matched active official TD listings |
| Realistic compensation and requirements | moderate | $69,700 to $98,400 CAD is standard for an entry level software role in Toronto |
| No warning signs in posting text | moderate | No requests for fees, banking details or identity documents |

### Tool calls

Run 1, saved as `reports/td.html`:

- `whois_lookup("td.com")`. Registered 1998-04-15, expires 2028-04-14,
  managed by CSC Corporate Domains. Established domain.
- `whois_lookup("myworkdayjobs.com")`. Registered 2014-03-13. The agent chose
  this itself. It was not in the seed domain list.
- `web_search` for the team and role. Exact query not logged.

Domains checked on run 1: myworkdayjobs.com and td.com.

The stored run checked td.com only. So the second lookup was not repeated on
every run.

The myworkdayjobs.com lookup is the part I care about. Nothing told the agent
to check the application portal. It worked out on its own that a posting is
only as trustworthy as where it sends you to apply, and verified that
separately.

## Fraudulent case: Junior Software Developer, NorthBridge Digital Solutions

Source: `postings-test/fake-junior-dev-northbridge.pdf`
Stored run: `data/applications/junior-software-developer-northbridge-digital-solutions-inc.json`

Verdict: red. Six signals, all negative. Headline: "This posting is a highly
dangerous identity theft and advance-fee scam."

| Signal | Weight | Evidence |
| :-- | :-- | :-- |
| Unregistered domain listed in posting | strong | northbridge-digitalsolutions-careers.com has no registration record and does not exist |
| Upfront request for sensitive personal information | strong | Asks for SIN, banking details, date of birth and scanned government ID |
| Advance-fee equipment purchase | strong | "purchase a company-approved laptop and software licence package ($1,200 CAD, reimbursed after 90 days)" |
| Free email address for corporate hiring | strong | Applications directed to northbridge.hiring2026@gmail.com |
| Unrealistically high salary for no experience | strong | $145,000 to $180,000 CAD plus signing bonus for a junior role needing "basic computer skills" |
| Bypassing the job board application portal | moderate | "Do not apply through this job board, applications sent through the portal will not be reviewed" |

Every red flag I planted was caught. Nothing was missed.

### Tool calls

First run, at the time the fake was first tested:

- `whois_lookup("northbridge-digitalsolutions-careers.com")`. The seed domain
  taken from the posting text. RDAP timed out and the lookup fell back to the
  system whois binary, which returned no record. Unregistered.
- `web_search` for the company name. This turned up a similarly named domain
  registered 2026-03-02, which is recent.

Rerun after the red verdict handling was added, which is the run now stored:

- `whois_lookup("northbridge-digitalsolutions-careers.com")`. RDAP returned
  404 this time rather than timing out, then whois confirmed no record.
- `web_search` for the company name, twice.
- Domains checked: the seed domain only. The second domain was not looked up
  on this run.

The two runs did not make identical tool calls. Both reached red with the same
core evidence.

## My judgement

I trust the legitimacy agent most out of everything the system produces. It
caught every red flag I planted in the fake posting. On the real posting it
investigated beyond the seed domain on its own and checked the application
portal I had not thought to check.

The domain lookup is what makes it work. An unregistered domain is a hard
fact, not a judgement call, and it is the kind of thing I would not have
checked by hand.

I would trust the verdict as a first pass. I would not treat it as the final
word. I would still verify the company myself before sending any personal
information, because the cost of the agent being wrong once is my SIN and my
banking details, and no amount of green verdicts is worth that.

The two runs on the fake posting did not check the same domains, which is a
reminder that the agent decides what to investigate each time. A green verdict
means it did not find a problem. It does not mean it looked everywhere.
