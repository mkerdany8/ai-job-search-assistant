# Extraction Spot Check

Two postings checked by hand against the source PDFs in `postings/`.
"Expected" is what the posting actually says. "Extracted" is what is stored in
`data/jobs/`.

## Software Engineer, IBM

Source: `postings/software-engineer-ibm.pdf`
Extracted: `data/jobs/software-engineer-ibm.json`

| Field | Expected | Extracted | Correct? |
| :-- | :-- | :-- | :-- |
| job_title | Software Engineer | Software Engineer | Yes |
| company_name | IBM | IBM | Yes |
| location | Toronto, ON | Toronto, ON | Yes |
| remote_status | Remote | remote | Yes |
| required_skills | Java, Kubernetes, cloud platforms, networking, security | Java, Kubernetes, cloud platforms | No. Missed networking and security. |
| preferred_skills | AWS, GCP, Azure | AWS, GCP, Azure | Yes |
| experience | 1+ years of relevant software development experience | min_years 1, seniority "not stated" | Yes |
| education | BS Degree in Computer Science, Engineering, or equivalent experience | BS Degree in Computer Science, Engineering, or equivalent experience | Yes |
| salary | 113.2K to 130.2K CAD/yr | 113200 to 130200 CAD yearly | Yes |

### Notes

The requirements are written as one run-on prose block with no bullet
separators in the extracted text. The relevant line is:

> Familiarity with cloud-native technology, including networking & security

Networking and security are named technical areas and belong in
required_skills. Both were dropped. The next clause in the same paragraph is
"Experience with Java, Kubernetes, and cloud platforms is highly valued", and
all three of those were extracted. So the model read the paragraph and took
the items from the end of it but not the middle.

Two other things I noticed while checking. The BS Degree line sits under the
heading "Preferred Technical And Professional Experience" in the source, not
under the required heading, and the posting separately lists "Preferred
Education: Master's Degree". The extraction reported the BS Degree as the
education requirement. I am calling that correct because it is the degree the
posting asks for, but the schema has one education field and the posting has
two education statements, so some information is lost either way.

## Junior Software Engineer, Scotiabank

Source: `postings/junior-software-engineer-scotiabank.pdf`
Extracted: `data/jobs/junior-software-engineer-scotiabank.json`

| Field | Expected | Extracted | Correct? |
| :-- | :-- | :-- | :-- |
| job_title | Junior Software Engineer | Junior Software Engineer | Yes |
| company_name | Scotiabank | Scotiabank | Yes |
| location | Toronto, ON | Toronto, ON | Yes |
| remote_status | not listed | not listed | Yes |
| required_skills | One of Java, JavaScript or Python. Relational and NoSQL databases, examples given as MySQL, PostgreSQL, MongoDB. RESTful APIs. CI/CD. Version control (Git). | Java, JavaScript, Python, MySQL, PostgreSQL, MongoDB, RESTful APIs, CI/CD, Git | Partly. Nine entries for five requirements. |
| preferred_skills | Interest in cloud platforms such as GCP and Azure | GCP, Azure | Yes |
| experience | not stated | min_years null, seniority "junior" | Yes |
| education | not listed | null | Yes |
| salary | not listed | all null | Yes |

### Notes

The posting says:

> Familiarity with at least one programming language such as Java,
> JavaScript, Python

That is one requirement satisfied by any one of three languages. Extraction
turned it into three separate required skills. The same happens with the
database line, where three examples given in brackets become three separate
required skills.

This matters for scoring and not just for tidiness. A candidate who knows Java
satisfies the language requirement in full, but the fit scorer sees one of
three matched and two missing.

Run to run variation on this same PDF: one run returned 11 required skills and
another returned 9. The stored run is the 9 entry version and lists the
database instances only. The 11 entry run listed the category "relational
databases" alongside PostgreSQL and MySQL, so the same requirement was counted
twice. That run was observed during testing and is not saved in the repo, so
the exact list for it is not logged.

## What this tells me

Extraction is accurate on the fields that are stated plainly and in one place.
Job title, company, location, salary, education and experience were right in
both postings.

It is unreliable on skills, in two specific ways. It drops named skills that
are buried mid paragraph, and it splits one requirement into several entries
when the posting offers a choice or gives examples. Both distort the skill
count, and the fit score is built on that count.
