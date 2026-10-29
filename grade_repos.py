#!/usr/bin/env python3
"""
Grade a list of student repos for assignment 4 (USART2 + DMA) - static, binary and
hardware tests - and write one report with the points and the failed checks of each.

    python grade_repos.py https://github.com/xsokolovae1/STM32,https://github.com/a/b
    python grade_repos.py -f repos.txt
    python grade_repos.py --collect grading-20261029-1012     # finish a timed-out batch

A repo URL may name the branch and the project folder explicitly:

    https://github.com/owner/repo/tree/zadanie4            branch zadanie4
    https://github.com/owner/repo/tree/main/cv4            branch main, folder cv4/
    https://github.com/owner/repo@zadanie4                 branch zadanie4

Otherwise the branch whose name looks like assignment 4 (zadanie4, zadanie_cv4, cv4 ...)
is used, falling back to the default branch, and the project folder is wherever
Src/usart.c and Inc/usart.h are.

How it works: every repo becomes one run of the "Batch grading (cv4)" workflow on the
orphan branch cv4-grader of DaverSVK/testing123, started by pushing an empty commit
whose message is the job. The workflow overlays the student's Src/ and Inc/ onto the
zadanie_cv4 baseline, builds, runs the static + binary tests on GitHub's runners and
flashes + tests the board on the Raspberry Pi runner. Points are computed from the
GRADE_GROUPS of the baseline's own cv4/grade_assignment.py.

Needs: the GitHub CLI (gh), logged in with push access to DaverSVK/testing123.
"""

import argparse
import base64
import datetime
import io
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

GRADER_REPO = "DaverSVK/testing123"
GRADER_BRANCH = "cv4-grader"
BASELINE = "zadanie_cv4"
RUN_BRANCH_PREFIX = "grade/cv4/"
BRANCH_PATTERN = r"(zadanie|cv|uloha|task)[ _-]*(cv)?[ _-]*0?4(?!\d)"
PROJECT_MARKERS = ("Src/usart.c", "Inc/usart.h")
POLL_S = 20


def log(message=""):
    print(message, flush=True)


# -- gh plumbing --------------------------------------------------------------

class GhError(RuntimeError):
    pass


def gh(*args, raw=False, check=True):
    result = subprocess.run(["gh", *args], capture_output=True)
    if check and result.returncode != 0:
        raise GhError(result.stderr.decode("utf-8", "replace").strip()
                      or "gh %s failed" % " ".join(args))
    if raw:
        return result.stdout
    text = result.stdout.decode("utf-8", "replace")
    return json.loads(text) if text.strip() else None


def api(path, *fields, method=None, raw=False, check=True):
    args = ["api", path]
    if method:
        args += ["-X", method]
    for field in fields:
        args += ["-f", field]
    return gh(*args, raw=raw, check=check)


# -- Resolving what to grade --------------------------------------------------

def parse_url(url):
    """owner, name, explicit ref + subdir path (or None)."""
    url = url.strip().rstrip("/")
    explicit = None
    if "@" in url.split("github.com", 1)[-1]:
        url, explicit = url.rsplit("@", 1)
    m = re.match(r"^(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?"
                 r"(?:/tree/(.+))?$", url)
    if not m:
        m = re.match(r"^([\w.-]+)/([\w.-]+)$", url)
        if not m:
            raise ValueError("not a GitHub repo URL: %s" % url)
        return m.group(1), m.group(2), explicit
    return m.group(1), m.group(2), explicit or m.group(3)


def resolve(url):
    """Everything the workflow needs to grade one repo."""
    owner, name, explicit = parse_url(url)
    repo = "%s/%s" % (owner, name)
    info = api("repos/%s" % repo)
    heads = {b["name"]: b["commit"]["sha"]
             for b in api("repos/%s/branches?per_page=100" % repo)}
    branches = list(heads)
    notes = []

    subdir = None
    if explicit:
        # tree/<branch>/<path> - branch names may contain '/', so try the longest first.
        parts = explicit.split("/")
        for i in range(len(parts), 0, -1):
            if "/".join(parts[:i]) in branches:
                ref = "/".join(parts[:i])
                subdir = "/".join(parts[i:]) or None
                break
        else:
            raise ValueError("branch '%s' does not exist in %s" % (explicit, repo))
    else:
        matching = [b for b in branches if re.search(BRANCH_PATTERN, b, re.IGNORECASE)]
        if matching:
            ref = sorted(matching, key=len)[0]
            if len(matching) > 1:
                notes.append("several assignment-4 branches (%s), graded '%s'"
                             % (", ".join(matching), ref))
        else:
            ref = info["default_branch"]

    # By SHA - a branch name with '/' in it does not survive the URL path.
    sha = heads[ref]
    tree = api("repos/%s/git/trees/%s?recursive=1" % (repo, sha))
    paths = {entry["path"] for entry in tree.get("tree", []) if entry["type"] == "blob"}
    if tree.get("truncated"):
        notes.append("repo tree too large to list completely")

    if subdir is None:
        candidates = []
        for path in paths:
            if path.endswith(PROJECT_MARKERS[0]):
                root = path[: -len(PROJECT_MARKERS[0])].rstrip("/")
                if all((root + "/" + m if root else m) in paths for m in PROJECT_MARKERS):
                    candidates.append(root)
        if not candidates:
            raise ValueError("no project with %s on branch '%s'"
                             % (" + ".join(PROJECT_MARKERS), ref))
        hinted = [c for c in candidates if re.search(BRANCH_PATTERN + "|usart|dma", c,
                                                      re.IGNORECASE)]
        subdir = sorted(hinted or candidates, key=lambda c: (c.count("/"), len(c)))[0]
        if len(candidates) > 1:
            notes.append("several projects (%s), graded '%s'"
                         % (", ".join(c or "/" for c in candidates), subdir or "/"))
    elif not all("%s/%s" % (subdir, m) in paths for m in PROJECT_MARKERS):
        raise ValueError("no %s in '%s' on branch '%s'"
                         % (" + ".join(PROJECT_MARKERS), subdir, ref))

    return {"url": url, "repo": repo, "ref": ref, "subdir": subdir, "sha": sha,
            "notes": notes}


# -- Starting the runs ----------------------------------------------------------

def start_run(job, tag, hardware):
    """Empty commit on top of cv4-grader, message = the job, pushed to its own branch."""
    head = api("repos/%s/git/ref/heads/%s" % (GRADER_REPO, GRADER_BRANCH))["object"]["sha"]
    tree = api("repos/%s/git/commits/%s" % (GRADER_REPO, head))["tree"]["sha"]
    message = json.dumps({"repo": job["repo"], "ref": job["ref"], "subdir": job["subdir"],
                          "baseline": BASELINE, "hardware": hardware})
    commit = api("repos/%s/git/commits" % GRADER_REPO, "message=" + message,
                 "tree=" + tree, "parents[]=" + head, method="POST")["sha"]
    slug = re.sub(r"[^\w.-]+", "-", "%s-%s" % (job["repo"].replace("/", "-"), tag)).lower()
    branch = RUN_BRANCH_PREFIX + slug
    api("repos/%s/git/refs" % GRADER_REPO, "ref=refs/heads/" + branch, "sha=" + commit,
        method="POST")
    job.update(branch=branch, grader_commit=commit, run_id=None, state="queued")


def find_run(job):
    runs = api("repos/%s/actions/runs?branch=%s&event=push&per_page=5"
               % (GRADER_REPO, job["branch"]))["workflow_runs"]
    runs = [r for r in runs if r["head_sha"] == job["grader_commit"]]
    return runs[0] if runs else None


def jobs_of(run_id):
    return api("repos/%s/actions/runs/%s/jobs" % (GRADER_REPO, run_id))["jobs"]


def runner_online():
    try:
        runners = api("repos/%s/actions/runners" % GRADER_REPO)["runners"]
    except GhError:
        return None
    return any(r["status"] == "online" and
               {"self-hosted", "ARM64"} <= {l["name"] for l in r["labels"]} for r in runners)


# -- Collecting and scoring ---------------------------------------------------

def download_artifacts(job, dest):
    artifacts = api("repos/%s/actions/runs/%s/artifacts" % (GRADER_REPO, job["run_id"]))
    found = []
    for artifact in artifacts.get("artifacts", []):
        if artifact.get("expired"):
            continue
        target = dest / artifact["name"]
        blob = api("repos/%s/actions/artifacts/%s/zip" % (GRADER_REPO, artifact["id"]),
                   raw=True)
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            archive.extractall(target)
        found.append(artifact["name"])
    return found


def junit_results(path):
    """{test name: (passed, one-line message)} from a pytest --junitxml file."""
    results = {}
    if not path.exists():
        return results
    for case in ET.parse(path).getroot().iter("testcase"):
        bad = case.find("failure")
        if bad is None:
            bad = case.find("error")
        if bad is None:
            results[case.get("name")] = (True, "")
        else:
            text = (bad.get("message") or bad.text or "").strip()
            first = next((line for line in text.splitlines() if line.strip()), "")
            first = re.sub(r"^(AssertionError|assert)\s*:?\s*", "", first)
            results[case.get("name")] = (False, first[:300])
    return results


_groups_cache = {}


def grade_groups():
    """GRADE_GROUPS & co. of the baseline's grade_assignment.py - the official split."""
    if not _groups_cache:
        blob = api("repos/%s/contents/cv4/grade_assignment.py?ref=%s"
                   % (GRADER_REPO, BASELINE), raw=True, check=True)
        source = json.loads(blob.decode("utf-8"))
        code = base64.b64decode(source["content"]).decode("utf-8")
        namespace = {"__file__": "tests/grade_assignment.py", "__name__": "grade_groups"}
        exec(compile(code, "grade_assignment.py", "exec"), namespace)
        _groups_cache.update(groups=namespace["GRADE_GROUPS"],
                             prereq=namespace.get("PREREQUISITES"),
                             dma=namespace.get("DMA_CHECKS"),
                             total=namespace.get("TOTAL_POINTS"))
    return _groups_cache


def test_name(node_id):
    return node_id.rsplit("::", 1)[-1]


def score(job, workdir):
    ws = workdir / "workspace"
    hw_dir = workdir / "hardware"
    status_file = ws / "results" / "status.txt"
    job["setup"] = status_file.read_text().strip() if status_file.exists() else None
    job["built"] = (ws / "build" / "usart_DMA.elf").exists()

    static = junit_results(ws / "results" / "static.xml")
    binary = junit_results(ws / "results" / "binary.xml")
    tests = dict(static)
    tests.update(binary)

    hardware = None
    if (hw_dir / "hardware-results.json").exists():
        hardware = json.loads((hw_dir / "hardware-results.json").read_text(encoding="utf-8"))

    def passes(group):
        for node in group["pytest"]:
            ok, _ = tests.get(test_name(node), (False, "not run"))
            if not ok:
                return False
        return all(hardware is not None and hardware.get(key) == "PASS"
                   for key in group["hardware"])

    info = grade_groups()
    job["groups"] = [{"name": g["name"], "max": g["points"],
                      "points": g["points"] if passes(g) else 0.0,
                      "needs_hardware": bool(g["hardware"])} for g in info["groups"]]
    job["total"] = sum(g["points"] for g in job["groups"])
    job["max_total"] = info["total"] or sum(g["max"] for g in job["groups"])
    job["prerequisites_ok"] = passes(info["prereq"]) if info["prereq"] else None
    job["dma_ok"] = passes(info["dma"]) if info["dma"] else None

    job["failed_static"] = [(n, m) for n, (ok, m) in static.items() if not ok]
    job["failed_binary"] = [(n, m) for n, (ok, m) in binary.items() if not ok]
    job["build_errors"] = []
    if not job["built"] and (ws / "results" / "build.log").exists():
        lines = (ws / "results" / "build.log").read_text(errors="replace").splitlines()
        job["build_errors"] = [l for l in lines if re.search(r"\berror\b", l)][:8]

    job["hardware"] = None
    if hardware is not None:
        job["hardware"] = {
            "overall": hardware.get("overall"),
            "failed": [{k: d.get(k) for k in ("phase", "name", "sent", "expected", "got",
                                             "info")}
                       for d in hardware.get("details", []) if d.get("result") == "FAIL"],
            "period_s": hardware.get("periodic_period_s"),
            "cases": "%s/%s" % (hardware.get("cases_passed"), hardware.get("cases_total")),
        }
    flash_log = hw_dir / "results" / "flash.log"
    job["flash_failed"] = hardware is None and flash_log.exists()


# -- Report -------------------------------------------------------------------

def hardware_state(job):
    if job.get("error"):
        return "-"
    if job.get("hardware"):
        return job["hardware"]["overall"]
    if "groups" not in job:
        return "PENDING" if job.get("state") != "completed" else "no result"
    if not job.get("built"):
        return "not run (no build)"
    if not job.get("with_hardware"):
        return "skipped (--no-hardware)"
    if job.get("flash_failed"):
        return "flashing failed"
    if job.get("state") != "completed":
        return "PENDING"
    return "no result"


def fmt(points):
    return ("%.2f" % points).rstrip("0").rstrip(".")


def write_report(jobs, out):
    lines = ["# Assignment 4 grading - %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
             "", "| Repo | Branch | Points | Hardware |", "|---|---|---:|---|"]
    for job in jobs:
        if job.get("error"):
            lines.append("| %s | - | **error** | - |" % job.get("repo", job["url"]))
            continue
        total = ("%s / %s" % (fmt(job["total"]), fmt(job["max_total"]))
                 if "total" in job else "pending")
        lines.append("| %s | `%s` | **%s** | %s |"
                     % (job["repo"], job["ref"], total, hardware_state(job)))

    for job in jobs:
        lines += ["", "---", "", "## %s" % job.get("repo", job["url"]), ""]
        if job.get("error"):
            lines += ["**Not graded:** %s" % job["error"]]
            continue
        lines.append("- Branch `%s`, folder `%s`, commit `%s`"
                     % (job["ref"], job["subdir"] or "/", job["sha"][:7]))
        if job.get("run_url"):
            lines.append("- Run: %s" % job["run_url"])
        for note in job.get("notes", []):
            lines.append("- Note: %s" % note)
        if job.get("setup") not in (None, "ok"):
            lines += ["", "**Not graded:** %s" % job["setup"]]
            continue
        if "groups" not in job:
            lines += ["", "**No results yet** (run state: %s)" % job.get("state")]
            continue

        lines += ["", "| Category | Points |", "|---|---:|"]
        for group in job["groups"]:
            mark = "✅" if group["points"] else "❌"
            lines.append("| %s | %s %s / %s |" % (group["name"], mark, fmt(group["points"]),
                                                 fmt(group["max"])))
        lines.append("| **Total** | **%s / %s** |" % (fmt(job["total"]), fmt(job["max_total"])))

        if not job["built"]:
            lines += ["", "**The firmware does not build** - binary and hardware tests "
                          "were not run."]
            lines += ["```"] + job["build_errors"] + ["```"] if job["build_errors"] else []
        if job.get("dma_ok") is False:
            lines += ["", "> The reception does not run on DMA + interrupts."]
        if job.get("prerequisites_ok") is False:
            lines += ["", "> The project does not build cleanly or the template files "
                          "were changed."]

        for title, failed in (("Failed static tests", job["failed_static"]),
                              ("Failed binary tests", job["failed_binary"])):
            if failed:
                lines += ["", "### %s (%d)" % (title, len(failed)), ""]
                lines += ["- `%s` - %s" % (n, m) if m else "- `%s`" % n for n, m in failed]

        state = hardware_state(job)
        lines += ["", "### Hardware: %s" % state]
        hw = job.get("hardware")
        if hw:
            lines.append("")
            lines.append("- input edge cases %s, periodic message every %s s"
                         % (hw["cases"], hw["period_s"]))
            for d in hw["failed"]:
                lines.append("- ❌ `%s/%s` - %s" % (d["phase"], d["name"], d.get("info") or ""))
                if d.get("sent") and d["sent"] != "<nothing>":
                    lines.append("  - sent `%s`, expected `%s`, got `%s`"
                                 % (d["sent"], d.get("expected"), d.get("got")))
        elif state == "PENDING":
            lines += ["", "The Raspberry Pi job has not finished - the hardware groups are "
                          "counted as 0 for now. Finish with `--collect %s`." % out]

    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "report.json").write_text(json.dumps(jobs, indent=2), encoding="utf-8")


def print_summary(jobs):
    log()
    width = max([len(j.get("repo", j["url"])) for j in jobs] + [4])
    for job in jobs:
        name = job.get("repo", job["url"]).ljust(width)
        if job.get("error"):
            log("  %s  ERROR    %s" % (name, job["error"]))
        elif job.get("setup") not in (None, "ok"):
            log("  %s  ERROR    %s" % (name, job["setup"]))
        elif "total" in job:
            failed = len(job["failed_static"]) + len(job["failed_binary"])
            hw_failed = len(job["hardware"]["failed"]) if job.get("hardware") else 0
            log("  %s  %4s/%s  tests failed: %d static/binary, %d hardware  [hw: %s]"
                % (name, fmt(job["total"]), fmt(job["max_total"]), failed, hw_failed,
                   hardware_state(job)))
        else:
            log("  %s  pending  (%s)" % (name, job.get("state")))


# -- Main loop ----------------------------------------------------------------

def save_state(jobs, out):
    (out / "state.json").write_text(json.dumps(jobs, indent=2), encoding="utf-8")


def wait_and_collect(jobs, out, deadline, cleanup):
    active = [j for j in jobs if not j.get("error") and not j.get("collected")]
    last = {}
    while active:
        for job in list(active):
            run = find_run(job) if not job.get("run_id") else \
                api("repos/%s/actions/runs/%s" % (GRADER_REPO, job["run_id"]))
            if run is None:
                continue
            job["run_id"], job["run_url"] = run["id"], run["html_url"]
            job["state"] = run["status"]
            if run["status"] != "completed":
                progress = ", ".join(
                    "%s: %s" % ("hardware" if "Raspberry" in j["name"] else "analysis",
                                j["status"]) for j in jobs_of(run["id"]))
            else:
                progress = "done (%s)" % run["conclusion"]
            if last.get(job["repo"]) != progress:
                log("  %-32s %s" % (job["repo"], progress))
                last[job["repo"]] = progress
            if run["status"] == "completed":
                collect(job, out, cleanup)
                active.remove(job)
        save_state(jobs, out)
        if not active:
            break
        if time.time() > deadline:
            log("\nTimeout - %d run(s) still going. Collecting what exists so far." % len(active))
            for job in active:
                if job.get("run_id"):
                    collect(job, out, cleanup=False, final=False)
            break
        time.sleep(POLL_S)
    save_state(jobs, out)


def collect(job, out, cleanup, final=True):
    workdir = out / re.sub(r"[^\w.-]+", "-", job["repo"])
    try:
        names = download_artifacts(job, workdir)
        if "workspace" in names:
            score(job, workdir)
    except (GhError, OSError, ValueError, ET.ParseError) as exc:
        job["error"] = "collecting the results failed: %s" % exc
    job["collected"] = final
    if final and cleanup and job.get("branch"):
        api("repos/%s/git/refs/heads/%s" % (GRADER_REPO, job["branch"]), method="DELETE",
            check=False)


def read_urls(args):
    urls = []
    for item in args.urls:
        urls += [u for u in re.split(r"[,\s]+", item) if u]
    if args.file:
        for line in Path(args.file).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0]
            urls += [u for u in re.split(r"[,\s]+", line) if u]
    seen = set()
    return [u for u in urls if not (u in seen or seen.add(u))]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("urls", nargs="*", help="repo URLs (space or comma separated)")
    parser.add_argument("-f", "--file", help="file with one repo URL per line")
    parser.add_argument("-o", "--out", help="output folder (default grading-<timestamp>)")
    parser.add_argument("--no-hardware", action="store_true",
                        help="skip the Raspberry Pi test (hardware groups score 0)")
    parser.add_argument("--timeout", type=float,
                        help="minutes to wait for the runs (default 20 + 3 per repo)")
    parser.add_argument("--keep-branches", action="store_true",
                        help="do not delete the grade/cv4/* trigger branches afterwards")
    parser.add_argument("--collect", metavar="DIR",
                        help="finish a previous batch whose runs were still going")
    args = parser.parse_args()

    if args.collect:
        out = Path(args.collect)
        jobs = json.loads((out / "state.json").read_text(encoding="utf-8"))
        log("Collecting %d repo(s) from %s" % (len(jobs), out))
    else:
        urls = read_urls(args)
        if not urls:
            parser.error("no repo URLs given")
        out = Path(args.out or datetime.datetime.now().strftime("grading-%Y%m%d-%H%M%S"))
        out.mkdir(parents=True, exist_ok=True)
        hardware = not args.no_hardware

        if hardware:
            online = runner_online()
            if online is False:
                log("WARNING: the Raspberry Pi runner is OFFLINE - the hardware tests will wait "
                    "for it.\n         Use --no-hardware to grade without them, or "
                    "--collect later.\n")

        tag = datetime.datetime.now().strftime("%m%d%H%M%S")
        jobs = []
        log("Resolving %d repo(s)" % len(urls))
        for url in urls:
            try:
                job = resolve(url)
            except (ValueError, GhError) as exc:
                job = {"url": url, "error": str(exc)}
                log("  %-40s ERROR %s" % (url, exc))
                jobs.append(job)
                continue
            job["with_hardware"] = hardware
            try:
                start_run(job, tag, hardware)
                log("  %-32s branch %s, folder %s -> started"
                    % (job["repo"], job["ref"], job["subdir"] or "/"))
            except GhError as exc:
                job["error"] = "could not start the run: %s" % exc
                log("  %-32s ERROR %s" % (job["repo"], job["error"]))
            jobs.append(job)
        save_state(jobs, out)

    timeout = args.timeout if args.timeout is not None else 20 + 3 * len(jobs)
    log("\nWaiting for the runs (up to %d min)..." % timeout)
    wait_and_collect(jobs, out, time.time() + timeout * 60, cleanup=not args.keep_branches)

    write_report(jobs, out)
    print_summary(jobs)
    log("\nReport: %s" % (out / "report.md").resolve())
    pending = [j for j in jobs if not j.get("error") and not j.get("collected")]
    if pending:
        log("%d run(s) unfinished - rerun with: python %s --collect %s"
            % (len(pending), Path(sys.argv[0]).name, out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
