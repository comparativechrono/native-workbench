#!/usr/bin/env python3
"""Promote the accepted 0.8.0 archives without rebuilding or replacing releases.

--prepare-only performs the identical local integrity/evidence preparation, with
no network requests or GitHub writes. Created tags/releases are never deleted:
prepublication failures keep the draft; postpublication failures keep the public
release and an incomplete public-download verification receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = "comparativechrono/workbench"
TAG = "app-v0.8.0"
SOURCE = "b3928ca6a29d22b5f010a303658c2e19c24324da"
RUN = 37453380541
PUBLISHED_COMMIT = "6fa1886b2027cfe634d9f9234fff773cd6c646d0"
PUBLISHED_RELEASE = 404720508
PROMOTION_RUN = 37468900068
PROMOTION_ARTIFACT = (11415239631, 78049210, "5f5b4b5a8d8e99858ae7d509b24fe3f07b96ed7137b96bb09c9c4835b4fd0cf2")
ARTIFACTS = {
    11408021439: ("candidate.zip", 75599305, "234688eabc01315aceba6fd588094bc7bf2263670766d0bdc9d088f8f0c735c1"),
    11408610523: ("scroll-frames.zip", 227642, "6586c47e262a4edb950a35ef2e2d01c09cccd144c9c8a235aaf3a1283e795203"),
    11408585481: ("windows-ordinary.zip", 1251294, "f3bd46da0eb6dd81c4d9075c07f355486f484b984b467e317329e989793edf88"),
    11408091528: ("windows-spaces.zip", 1250035, "bf75a716b79225b4d1442ac80bc09a69be7d7b6a3c41d327187f3c32d29371d8"),
    11407866586: ("long-paths.zip", 87307, "27bc14a6d4390ca43a20023c14a2b50b5062fe53bebdd36a7c93a9b63b438e43"),
}
ARCHIVES = {
    "native-workbench-0.8.0-source.zip": (46243835, "c2590379b45d313acbcd5bbc41344b288aa6ad159804bf06dcbdcc9726adb22f"),
    "native-workbench-0.8.0-starter-windows.zip": (16948940, "df001a80033ff8e834045ec683c79672e0efdbd4880fb89fca8bf8c36d830fdc"),
    "native-workbench-0.8.0-update-from-0.6.0.zip": (12897242, "3dd146267b9a8300ba957c84914bc324ea537c05b09268b48381ae6a4d530e96"),
}
STARTER_SHA = ARCHIVES["native-workbench-0.8.0-starter-windows.zip"][1]
JOBS = {"build", "native-scroll-frames", "native (ordinary)", "native (path with spaces)", "native-long-paths"}
ROOT = Path(__file__).resolve().parents[1]


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def checked_zip(raw):
    archive = zipfile.ZipFile(io.BytesIO(raw))
    names = archive.namelist()
    require(len(names) == len(set(names)), "Duplicate ZIP members.")
    require(all(not PurePosixPath(n).is_absolute() and ".." not in PurePosixPath(n).parts
                and "\\" not in n for n in names), "Unsafe ZIP member.")
    require(archive.testzip() is None, "ZIP CRC validation failed.")
    return archive


def check_report(report, count):
    require(report.get("success") is True and report.get("nativeWindowsExecuted") is True
            and report.get("passed") == count and report.get("skips") == [], "Native gate did not pass completely.")
    require(report.get("sourceCommit") == SOURCE and report.get("assetSha256") == STARTER_SHA,
            "Native gate identifies different application bytes.")


def verify_source_identity(publish_sha):
    require(re.fullmatch(r"[0-9a-f]{40}", publish_sha), "Expected exact publishing commit.")
    subprocess.run(["git", "merge-base", "--is-ancestor", SOURCE, publish_sha], cwd=ROOT, check=True)
    changed = subprocess.check_output(["git", "diff", "--name-only", SOURCE, publish_sha], cwd=ROOT, text=True).splitlines()
    exceptions = {"README.md", "scripts/publish_app_080.py", "tests/test_publish_app_080.py",
                  ".github/workflows/publish-app-0.8.0.yml"}
    require(all(p.startswith(("knowledge/", "docs/")) or p in exceptions for p in changed),
            "Application, gate, build or pack code changed after the accepted candidate: " + repr(changed))


def prepare(input_dir, output_dir, publish_sha, online_evidence=None):
    verify_source_identity(publish_sha)
    require(not output_dir.exists() or not any(output_dir.iterdir()), "Promotion output must be empty.")
    output_dir.mkdir(parents=True, exist_ok=True)
    blobs = {}
    for identity, (name, size, digest) in ARTIFACTS.items():
        raw = (input_dir / name).read_bytes()
        require(len(raw) == size and sha(raw) == digest, "Artifact identity mismatch: " + name)
        with checked_zip(raw):
            pass
        blobs[identity] = raw
    with checked_zip(blobs[11408021439]) as candidate:
        require(set(candidate.namelist()) == set(ARCHIVES) | {"BUILD-PROVENANCE.json", "SHA256SUMS.txt", "source-metadata.json"},
                "Candidate member inventory changed.")
        provenance = json.loads(candidate.read("BUILD-PROVENANCE.json"))
        require(provenance["sourceCommit"] == SOURCE, "Build provenance differs from accepted source.")
        sums = {}
        for line in candidate.read("SHA256SUMS.txt").decode().splitlines():
            digest, name = line.split("  ", 1)
            require(name not in sums, "Duplicate checksum row.")
            sums[name] = digest
        require(sums == {name: value[1] for name, value in ARCHIVES.items()}, "Candidate checksums differ.")
        for name, (size, digest) in ARCHIVES.items():
            raw = candidate.read(name)
            require(len(raw) == size and sha(raw) == digest, "Packaged archive identity differs: " + name)
            with checked_zip(raw) as archive:
                if name.endswith("starter-windows.zip"):
                    manifest = json.loads(archive.read("native-workbench/manifest.json"))
                    require(manifest["version"] == "0.8.0" and len(manifest["files"]) == 68, "Unexpected core inventory.")
                    for item in manifest["files"]:
                        content = archive.read("native-workbench/" + item["path"])
                        require(len(content) == item["bytes"] and sha(content) == item["sha256"], "Core file identity differs.")
        for name in candidate.namelist():
            (output_dir / name).write_bytes(candidate.read(name))
    reports = {}
    for identity, label in [(11408585481, "ordinary"), (11408091528, "spaces")]:
        with checked_zip(blobs[identity]) as archive:
            for kind, path, count in [("workspace", "workspace-ui-evidence/native-ui.json", 32),
                                      ("references", "workspace-reference-evidence/native-references.json", 8)]:
                report = json.loads(archive.read(path))
                check_report(report, count)
                reports[label + "-" + kind] = {"passed": count, "skips": [], "sha256": sha(archive.read(path)),
                                               "path": ARTIFACTS[identity][0] + ":" + path}
    with checked_zip(blobs[11408610523]) as archive:
        report = json.loads(archive.read("fixed/native-scroll-frames.json"))
        check_report(report, 3)
        require(report["applicationChecksPassed"] and len(report["panels"]) == 3, "Temporal gate incomplete.")
        require(sum(p["frames"] for p in report["panels"]) == 960 and
                all(p["success"] and p["endpointFailures"] == 0 and p["unexpectedFrames"] == 0
                    and p["precisionPassed"] for p in report["panels"]), "Temporal assertions differ.")
        reports["temporal"] = {"passed": 3, "frames": 960, "precisionCases": 18,
                               "sha256": sha(archive.read("fixed/native-scroll-frames.json"))}
    with checked_zip(blobs[11407866586]) as archive:
        report = json.loads(archive.read("fixed/native-long-paths.json"))
        check_report(report, 3)
        require(len(report["outputFiles"]) == 20 and report["applicationCheck"]["corePassed"] == 7
                and report["applicationCheck"]["starterFailed"] == 0
                and report["applicationCheck"]["starterSkipped"] == 0, "Long-path scientific gate incomplete.")
        for item in report["outputFiles"]:
            require(sha(archive.read("fixed/" + item["evidenceFile"].replace("\\", "/"))) == item["sha256"],
                    "Retained scientific output identity differs.")
        reports["longPaths"] = {"passed": 3, "rehashedOutputs": 20,
                                "sha256": sha(archive.read("fixed/native-long-paths.json"))}
    with zipfile.ZipFile(output_dir / "WINDOWS-EVIDENCE.zip", "w", zipfile.ZIP_DEFLATED) as evidence:
        for identity, (name, _, _) in ARTIFACTS.items():
            if identity != 11408021439:
                evidence.writestr("original-ci-artifacts/" + name, blobs[identity])
        evidence_names = ["native-workflow-0.8.0-scroll-2026-10-06.json",
                          "native-ui-0.8.0-release-readiness-2026-10-06.json"]
        for name in evidence_names:
            evidence.write(ROOT / "knowledge/evidence" / name, "repository-evidence/" + name)
        if online_evidence:
            evidence.writestr("promotion-run-verification.json", json_bytes(online_evidence))
    validation = {
        "schema": 1, "version": "0.8.0", "releaseTag": TAG, "packagedSourceCommit": SOURCE,
        "publicationCommit": publish_sha, "acceptedRunId": RUN,
        "acceptedRunUrl": f"https://github.com/{REPOSITORY}/actions/runs/{RUN}",
        "recordedUtc": datetime.now(timezone.utc).isoformat(), "archivesRebuilt": False,
        "candidateArtifacts": [{"id": k, "file": v[0], "bytes": v[1], "sha256": v[2]} for k, v in ARTIFACTS.items()],
        "sourceChecks": {"passed": 82, "failures": 0, "skips": 0, "platform": "Linux CI"},
        "nativeReports": reports,
        "testerAcceptance": {"reportedBy": "Project owner", "date": "2026-10-06",
                             "statement": "Testers are happy with the accepted candidate; publication authorized."},
        "scope": "Reuse exact accepted candidate native evidence; promotion verifies immutable archives and release downloads. No new native execution is claimed.",
        "limits": ["Hosted native display tests used Windows Server 2022, 96 DPI. Physical tester acceptance is user-reported; no tester hardware details were supplied.",
                   "Old and new packages both had zero unexpected frames in finite CI sampling; CI did not reproduce the reported visual flashing. Precision-wheel failure was reproduced and corrected.",
                   "Finite frame samples mask edit/button animation and cannot exclude between-sample flashes; no general high-DPI, multi-monitor or physical-trackpad claim.",
                   "Migration was verified from 0.6.0 only. No 0.7.0-to-0.8.0 updater is included or claimed.",
                   "Long-path validation covers recorded starter outputs, not every optional tool or native folder picker."],
        "originalCompanions": "BUILD-PROVENANCE and source archive retain immutable creation-time candidate/pending statements; this later record supplies completed evidence.",
        "assets": [{"file": p.name, "bytes": p.stat().st_size, "sha256": sha(p.read_bytes())}
                   for p in sorted(output_dir.iterdir())],
    }
    (output_dir / "RELEASE-VALIDATION.json").write_bytes(json_bytes(validation))
    (output_dir / "EVIDENCE-SHA256SUMS.txt").write_text("".join(
        sha(p.read_bytes()) + "  " + p.name + "\n" for p in sorted(output_dir.iterdir()) if p.name not in ARCHIVES), encoding="utf-8")
    return validation


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, token):
        require(bool(token), "GitHub token is required for publication.")
        self.token = token
        self.base = "https://api.github.com/repos/" + REPOSITORY

    def api(self, path, method="GET", data=None, absent_ok=False):
        request = urllib.request.Request(self.base + path, method=method,
            data=None if data is None else json_bytes(data), headers={"Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json"})
        try:
            # API requests never follow redirects with the credential header.
            with urllib.request.build_opener(NoRedirect).open(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404 and absent_ok:
                return None
            raise RuntimeError(f"GitHub {method} {path} failed: HTTP {error.code}") from None

    def download(self, url, destination, expected_sha, expected_size, authenticated=False):
        # Actions' archive endpoint returns a storage redirect using the JSON
        # API media type. Release-asset endpoints instead need octet-stream.
        artifact_endpoint = re.fullmatch(re.escape(self.base) + r"/actions/artifacts/[0-9]+/zip", url)
        headers = {"Accept": "application/vnd.github+json" if artifact_endpoint else "application/octet-stream"}
        if authenticated:
            require(url.startswith(self.base + "/"), "Credentials only belong on this repository's API.")
            headers["Authorization"] = "Bearer " + self.token
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        opener = urllib.request.build_opener(NoRedirect)
        for _ in range(6):
            parsed = urllib.parse.urlparse(url)
            host = parsed.hostname or ""
            require(parsed.scheme == "https" and not parsed.username and not parsed.password and
                    (host in {"api.github.com", "github.com"} or
                     any(host.endswith(suffix) for suffix in
                         (".githubusercontent.com", ".blob.core.windows.net", ".amazonaws.com"))),
                    "Download left trusted HTTPS GitHub/storage hosts.")
            try:
                response = opener.open(urllib.request.Request(url, headers=headers), timeout=90)
                break
            except urllib.error.HTTPError as error:
                if error.code in (301, 302, 303, 307, 308):
                    url = urllib.parse.urljoin(url, error.headers["Location"])
                    # Signed GitHub storage redirects never receive the API token.
                    headers = {"Accept": "application/octet-stream"}
                    continue
                raise RuntimeError(f"Download failed: HTTP {error.code}") from None
        else:
            raise ValueError("Too many download redirects.")
        partial = destination.with_name(destination.name + ".partial")
        total = 0
        digest = hashlib.sha256()
        try:
            with response, partial.open("xb") as out:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    require(total <= expected_size, "Download exceeded pinned length.")
                    digest.update(chunk)
                    out.write(chunk)
            require(total == expected_size and digest.hexdigest() == expected_sha, "Downloaded identity differs.")
            partial.replace(destination)
        finally:
            partial.unlink(missing_ok=True)


class ReadOnlyGitHub(GitHub):
    def api(self, path, method="GET", data=None, absent_ok=False):
        require(method == "GET" and data is None, "Published-release verification permits GET requests only.")
        return super().api(path, method, data, absent_ok)


def verify_public_downloads(client, release_id, files, publish_sha, receipt_path, verification_only=False):
    # Draft asset browser URLs can name a temporary untagged release. Refresh
    # after publication and accept only the final canonical tagged URLs.
    published = client.api(f"/releases/{release_id}")
    require(published["id"] == release_id and published["tag_name"] == TAG and
            not published["draft"] and published["prerelease"], "Expected the existing published prerelease.")
    require(client.api("/git/ref/tags/" + TAG)["object"]["sha"] == publish_sha, "Published tag identity differs.")
    by_name = {a["name"]: a for a in published["assets"]}
    require(len(by_name) == len(published["assets"]) == len(files) and set(by_name) == {p.name for p in files},
            "Published asset inventory differs.")
    receipt = {"success": False, "phase": "public-download-verification", "verificationOnly": verification_only,
               "release": published["html_url"], "releaseId": release_id, "publicationCommit": publish_sha,
               "packagedSourceCommit": SOURCE, "publicDownloads": []}
    receipt_path.write_bytes(json_bytes(receipt))
    with tempfile.TemporaryDirectory(prefix="verify-workbench-public-") as temporary:
        for path in files:
            asset = by_name[path.name]
            digest = sha(path.read_bytes())
            expected_url = f"https://github.com/{REPOSITORY}/releases/download/{TAG}/" + urllib.parse.quote(path.name)
            require(asset["browser_download_url"] == expected_url and asset["state"] == "uploaded"
                    and asset["size"] == path.stat().st_size and asset["digest"] == "sha256:" + digest,
                    "Published asset metadata or canonical URL differs: " + path.name)
            for attempt in range(3):
                try:
                    client.download(expected_url, Path(temporary) / path.name, digest, path.stat().st_size)
                    break
                except RuntimeError as error:
                    if str(error) != "Download failed: HTTP 404" or attempt == 2:
                        raise
                    time.sleep((2, 5)[attempt])
            receipt["publicDownloads"].append({"file": path.name, "bytes": path.stat().st_size,
                                                "sha256": digest, "url": expected_url})
            receipt_path.write_bytes(json_bytes(receipt))
    require(client.api("/git/ref/tags/" + TAG)["object"]["sha"] == publish_sha, "Published tag identity changed.")
    receipt.update(success=True, phase="completed")
    receipt_path.write_bytes(json_bytes(receipt))
    return receipt


def recover_promotion_assets(raw, output_dir):
    require(len(raw) == PROMOTION_ARTIFACT[1] and sha(raw) == PROMOTION_ARTIFACT[2], "Retained promotion artifact identity differs.")
    require(not output_dir.exists() or not any(output_dir.iterdir()), "Verification output must be empty.")
    output_dir.mkdir(parents=True, exist_ok=True)
    names = set(ARCHIVES) | {"BUILD-PROVENANCE.json", "SHA256SUMS.txt", "source-metadata.json",
                             "WINDOWS-EVIDENCE.zip", "RELEASE-VALIDATION.json", "EVIDENCE-SHA256SUMS.txt"}
    with checked_zip(raw) as archive:
        members = {"promotion-assets/" + name for name in names} | {"public-download-verification.json"}
        require(set(archive.namelist()) == members, "Retained promotion artifact member inventory differs.")
        for name in names:
            (output_dir / name).write_bytes(archive.read("promotion-assets/" + name))
        prior = json.loads(archive.read("public-download-verification.json"))
        require(prior["publicationCommit"] == PUBLISHED_COMMIT and prior["packagedSourceCommit"] == SOURCE,
                "Retained publication receipt source differs.")
    for name, (size, digest) in ARCHIVES.items():
        raw = (output_dir / name).read_bytes()
        require(len(raw) == size and sha(raw) == digest, "Original accepted archive changed: " + name)
        with checked_zip(raw):
            pass
    for checksum, expected_names in [("SHA256SUMS.txt", set(ARCHIVES)),
                                      ("EVIDENCE-SHA256SUMS.txt", names - set(ARCHIVES) - {"EVIDENCE-SHA256SUMS.txt"})]:
        rows = [line.split("  ", 1) for line in (output_dir / checksum).read_text().splitlines()]
        require(len(rows) == len(expected_names) and {row[1] for row in rows} == expected_names,
                "Retained checksum member inventory differs.")
        require(all(sha((output_dir / name).read_bytes()) == digest for digest, name in rows), "Retained checksum verification failed.")
    validation = json.loads((output_dir / "RELEASE-VALIDATION.json").read_bytes())
    require(validation["packagedSourceCommit"] == SOURCE and validation["publicationCommit"] == PUBLISHED_COMMIT
            and validation["acceptedRunId"] == RUN and not validation["archivesRebuilt"], "Retained release validation identity differs.")
    require(len(validation["assets"]) == 7 and {a["file"] for a in validation["assets"]} ==
            names - {"RELEASE-VALIDATION.json", "EVIDENCE-SHA256SUMS.txt"}, "Retained validation inventory differs.")
    for item in validation["assets"]:
        raw = (output_dir / item["file"]).read_bytes()
        require(len(raw) == item["bytes"] and sha(raw) == item["sha256"], "Retained validation asset differs.")
    return sorted(output_dir.iterdir())


def verify_published(args):
    require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY and
            os.environ.get("GITHUB_REF") == "refs/heads/release/verify-app-0.8.0", "Wrong verification repository or branch.")
    require(args.publish_sha == PUBLISHED_COMMIT, "Verification must identify the existing published commit.")
    verify_source_identity(PUBLISHED_COMMIT)
    client = ReadOnlyGitHub(os.environ.get("GH_TOKEN"))
    verify_run(client)
    identity, size, digest = PROMOTION_ARTIFACT
    metadata = client.api(f"/actions/artifacts/{identity}")
    require(metadata["workflow_run"]["id"] == PROMOTION_RUN and metadata["workflow_run"]["head_sha"] == PUBLISHED_COMMIT
            and not metadata["expired"] and metadata["size_in_bytes"] == size and metadata["digest"] == "sha256:" + digest,
            "Retained promotion artifact metadata differs or expired.")
    args.input_dir.mkdir(parents=True, exist_ok=True)
    archive = args.input_dir / "retained-promotion.zip"
    client.download(client.base + f"/actions/artifacts/{identity}/zip", archive, digest, size, True)
    files = recover_promotion_assets(archive.read_bytes(), args.output_dir)
    receipt = verify_public_downloads(client, PUBLISHED_RELEASE, files, PUBLISHED_COMMIT, args.receipt, True)
    print(json.dumps({"verifiedExistingRelease": receipt["release"], "verifiedAssets": len(files), "remoteMutations": False}))


def verify_run(client):
    run = client.api(f"/actions/runs/{RUN}")
    require(run["head_sha"] == SOURCE and run["status"] == "completed" and run["conclusion"] == "success",
            "Accepted workflow is no longer a successful exact-source run.")
    data = client.api(f"/actions/runs/{RUN}/jobs?filter=latest&per_page=100")
    jobs = data["jobs"]
    require(data["total_count"] == len(jobs) == 5 and {j["name"] for j in jobs} == JOBS,
            "Unexpected accepted run job inventory.")
    require(all(j["conclusion"] == "success" and all(s["conclusion"] == "success" for s in j["steps"])
                for j in jobs), "Accepted run contains failed or skipped jobs/steps.")
    return {"runId": RUN, "sourceCommit": SOURCE, "conclusion": "success",
            "jobs": [{"id": j["id"], "name": j["name"], "conclusion": j["conclusion"]} for j in jobs]}


def publish(args):
    require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY and
            os.environ.get("GITHUB_REF") == "refs/heads/release/app-0.8.0", "Wrong publication repository or branch.")
    require(os.environ.get("GITHUB_SHA") == args.publish_sha, "Publishing commit differs from workflow SHA.")
    notes = (ROOT / "docs/releases/0.8.0.md").read_text(encoding="utf-8")
    require("0.8.0" in notes and len(notes) >= 200, "Release notes are missing or incomplete.")
    client = GitHub(os.environ.get("GH_TOKEN"))
    require(client.api("/git/ref/tags/" + TAG, absent_ok=True) is None and
            client.api("/releases/tags/" + TAG, absent_ok=True) is None, "Tag/release already exists; refusing replacement.")
    run = verify_run(client)
    args.input_dir.mkdir(parents=True, exist_ok=True)
    for identity, (name, size, digest) in ARTIFACTS.items():
        metadata = client.api(f"/actions/artifacts/{identity}")
        require(metadata["workflow_run"]["id"] == RUN and metadata["workflow_run"]["head_sha"] == SOURCE
                and not metadata["expired"] and metadata["size_in_bytes"] == size
                and metadata["digest"] == "sha256:" + digest, "Artifact metadata changed or expired.")
        client.download(client.base + f"/actions/artifacts/{identity}/zip", args.input_dir / name, digest, size, True)
    prepare(args.input_dir, args.output_dir, args.publish_sha, run)
    # The source identity and absent-tag checks precede every remote mutation.
    require(client.api("/git/ref/tags/" + TAG, absent_ok=True) is None and
            client.api("/releases/tags/" + TAG, absent_ok=True) is None, "Release appeared during preparation.")
    client.api("/git/refs", "POST", {"ref": "refs/tags/" + TAG, "sha": args.publish_sha})
    release = client.api("/releases", "POST", {"tag_name": TAG, "target_commitish": args.publish_sha,
        "name": "Native Workbench 0.8.0", "body": notes, "draft": True, "prerelease": True,
        "make_latest": "false"})
    files = sorted(args.output_dir.iterdir())
    subprocess.run(["gh", "release", "upload", TAG, *map(str, files), "--repo", REPOSITORY], check=True)
    uploaded = client.api(f"/releases/{release['id']}")
    require(uploaded["draft"] and uploaded["prerelease"], "Unexpected draft state.")
    by_name = {a["name"]: a for a in uploaded["assets"]}
    require(len(by_name) == len(uploaded["assets"]) == len(files) and set(by_name) == {p.name for p in files},
            "Uploaded asset inventory differs.")
    with tempfile.TemporaryDirectory(prefix="verify-workbench-release-") as temporary:
        for path in files:
            asset = by_name[path.name]
            require(asset["state"] == "uploaded" and asset["size"] == path.stat().st_size,
                    "Asset upload did not finish.")
            client.download(asset["url"], Path(temporary) / path.name, sha(path.read_bytes()), path.stat().st_size, True)
    require(client.api("/git/ref/tags/" + TAG)["object"]["sha"] == args.publish_sha,
            "Tag changed before publication; leaving the verified assets in draft.")
    published = client.api(f"/releases/{release['id']}", "PATCH", {"draft": False, "prerelease": True, "make_latest": "false"})
    require(not published["draft"] and published["prerelease"], "Release was not published as a prerelease.")
    verify_public_downloads(client, release["id"], files, args.publish_sha, args.receipt)
    print(json.dumps({"published": published["html_url"], "verifiedAssets": len(files)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--publish-sha", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--verify-published", action="store_true")
    parser.add_argument("--receipt", type=Path, default=Path("public-download-verification.json"))
    args = parser.parse_args()
    if args.prepare_only:
        prepare(args.input_dir, args.output_dir, args.publish_sha)
        print(json.dumps({"prepared": str(args.output_dir), "assets": len(list(args.output_dir.iterdir())), "networkWrites": False}))
    else:
        try:
            (verify_published if args.verify_published else publish)(args)
        except Exception as error:
            # Retain a diagnostic even if download fails before assets exist.
            # Preserve partial public verification if publishing already happened.
            receipt = json.loads(args.receipt.read_bytes()) if args.receipt.is_file() else {
                "phase": "promotion", "publicationCommit": args.publish_sha,
                "packagedSourceCommit": SOURCE, "publicDownloads": []}
            receipt.update(success=False, failureType=type(error).__name__,
                           error=str(error) if isinstance(error, (ValueError, RuntimeError)) else "See workflow log.",
                           recordedUtc=datetime.now(timezone.utc).isoformat())
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_bytes(json_bytes(receipt))
            raise


if __name__ == "__main__":
    main()
