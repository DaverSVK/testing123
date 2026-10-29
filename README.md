# cv4 batch grader

Orphan branch - shares no history with the `zadanie_cv*` assignment branches and is
never copied into student repos.

```
python grade_repos.py https://github.com/owner/repo,https://github.com/owner2/repo2
python grade_repos.py -f repos.txt [--no-hardware] [--timeout MIN]
python grade_repos.py --collect grading-<timestamp>
```

Each repo becomes one run of `.github/workflows/grade-cv4.yml`, started by an empty
commit pushed to `grade/cv4/<slug>` whose message is the job (JSON). The student's
`Src/` and `Inc/` are built on top of the `zadanie_cv4` baseline; static + binary tests
run on GitHub's runners, flashing + the hardware test on the Raspberry Pi runner.

Private student repos need a `STUDENT_REPO_TOKEN` secret (read access to them).
