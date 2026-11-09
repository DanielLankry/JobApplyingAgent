#!/usr/bin/env python3
"""One-off, explicitly leased Git history cleanup. Never prints matched values."""

from __future__ import annotations

import argparse
import base64
import importlib.metadata
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REQUEST_PATH = ".github/security-cleanup-request.json"
VERSION = "2.47.0"


class StopCleanup(Exception):
    pass


def command(arguments, *, cwd=None, data=None, env=None, stage="git-operation"):
    result = subprocess.run(arguments, cwd=cwd, input=data, capture_output=True, env=env)
    if result.returncode:
        # Do not print raw stderr: filenames, source text or credentials can appear there.
        reason = "command-rejected"
        lower = result.stderr.lower()
        for marker, label in [
            (b"protected", "protected-ref"),
            (b"stale info", "lease-conflict"),
            (b"workflow", "workflow-permission"),
            (b"atomic", "atomic-push-rejected"),
            (b"authentication", "authentication-failed"),
        ]:
            if marker in lower:
                reason = label
                break
        raise StopCleanup(f"{stage}: {reason}")
    return result.stdout


def git(repo, *args, data=None, env=None, stage="git-read"):
    return command(["git", "-C", str(repo), *args], data=data, env=env, stage=stage)


def refs(repo):
    result = {}
    for line in (
        git(repo, "for-each-ref", "--format=%(refname) %(objectname)").decode().splitlines()
    ):
        name, sha = line.split()
        result[name] = sha
    return result


def public_refs(values):
    return {
        name: sha for name, sha in values.items() if name.startswith(("refs/heads/", "refs/tags/"))
    }


def remote_refs(remote, env):
    output = command(["git", "ls-remote", "--refs", remote], env=env, stage="remote-ref-read")
    return {name: sha for sha, name in (line.split() for line in output.decode().splitlines())}


def safe_ref(name):
    return re.sub(r"\d{9}", "[ID-REDACTED]", name)


def selected_paths(repo, source):
    commit = source.get("commit", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise StopCleanup("Invalid configured source commit")
    if "path" in source:
        paths = [source["path"]]
    else:
        pattern = re.compile(source["path_regex"])
        paths = [
            p.decode()
            for p in git(repo, "ls-tree", "-r", "--name-only", "-z", commit).split(b"\0")
            if p and pattern.fullmatch(p.decode())
        ]
    if len(paths) != source.get("expected_paths", 1):
        raise StopCleanup("Historical source selector did not match expected path count")
    return paths


class Transform:
    def __init__(self, repo, config):
        self.rules = []
        self.renames = {}
        self.removed_exact = set()
        self.removed_prefixes = []
        for removal in config.get("remove_paths", []):
            if set(removal) not in ({"path"}, {"prefix"}):
                raise StopCleanup("Removal must specify exactly one path or prefix")
            path = removal.get("path", removal.get("prefix"))
            if not path or path.startswith("/") or ".." in Path(path).parts or path in (".", "./"):
                raise StopCleanup("Invalid historical removal path")
            if "prefix" in removal:
                if not path.endswith("/"):
                    raise StopCleanup("Removal prefixes must end with a directory separator")
                self.removed_prefixes.append(path.encode())
            else:
                self.removed_exact.add(path.encode())
        for source in config.get("sources", []):
            matches = []
            for path in selected_paths(repo, source):
                if source.get("extract_from") == "filename":
                    text = path
                else:
                    raw = git(
                        repo, "show", source["commit"] + ":" + path, stage="historical-source-read"
                    )
                    if source.get("decode") == "notebook_source":
                        notebook = json.loads(raw)
                        text = "\n".join(
                            "".join(c.get("source", [])) for c in notebook.get("cells", [])
                        )
                    else:
                        text = raw.decode("utf-8")
                for match in re.finditer(source["pattern"], text):
                    for group in source.get("groups", [1]):
                        matches.append(match.group(group))
            if len(matches) != source.get("expected_matches", 1):
                raise StopCleanup("Historical extraction did not match expected value count")
            for value in matches:
                if not source.get("min_length", 4) <= len(value) <= source.get("max_length", 4096):
                    raise StopCleanup("Historical extracted value has unexpected length")
                replacement = source.get("replacement", "REMOVED_CREDENTIAL")
                if value in replacement:
                    raise StopCleanup("Replacement would retain a sensitive value")
                scopes = [re.compile(p) for p in source.get("scope_paths", [])]
                mode = source.get("match_mode", "literal")
                if mode not in ("literal", "whole_word"):
                    raise StopCleanup("Unsupported value match mode")
                variants = {value}
                derived = source.get("derived_forms")
                if derived:
                    if derived != "israeli_phone":
                        raise StopCleanup("Unsupported derived value forms")
                    digits = re.sub(r"\D", "", value)
                    if not digits.startswith("972") or len(digits) != 12:
                        raise StopCleanup(
                            "Phone source does not match the expected international form"
                        )
                    local = "0" + digits[3:]
                    variants.update(
                        {
                            "+" + digits,
                            digits,
                            local,
                            " ".join((local[:3], local[3:6], local[6:])),
                            "-".join((local[:3], local[3:6], local[6:])),
                        }
                    )
                for variant in variants:
                    matcher = (
                        re.compile(
                            rb"(?<![A-Za-z0-9_@])"
                            + re.escape(variant.encode())
                            + rb"(?![A-Za-z0-9_@])"
                        )
                        if mode == "whole_word"
                        else None
                    )
                    self.rules.append(
                        (variant.encode(), replacement.encode(), scopes, source["id"], matcher)
                    )
        # Avoid replacing a short name inside a longer email or identifier first.
        self.rules.sort(key=lambda rule: -len(rule[0]))
        for rename in config.get("renames", []):
            for path in selected_paths(repo, rename):
                target = rename["new_path"]
                if not target or target.startswith("/") or ".." in Path(target).parts:
                    raise StopCleanup("Invalid rename target")
                self.renames[path.encode()] = target.encode()
        if not self.rules and not self.removed_exact and not self.removed_prefixes:
            raise StopCleanup("No cleanup rules configured")

    def removed(self, path):
        return path in self.removed_exact or any(
            path.startswith(prefix) for prefix in self.removed_prefixes
        )

    def filename(self, path):
        value = self.renames.get(path, path)
        for old, new, scopes, _, matcher in self.rules:
            if not scopes:
                value = (
                    matcher.sub(lambda _match, replacement=new: replacement, value)
                    if matcher
                    else value.replace(old, new)
                )
        return value

    def content(self, data, path=None):
        result = data
        # Replace full filenames first so historical README/project references stay useful.
        for old, new in sorted(self.renames.items(), key=lambda pair: -len(pair[0])):
            result = result.replace(old, new)
        for old, new, scopes, _, matcher in self.rules:
            if scopes and (
                path is None or not any(p.search(path.decode("utf-8", "replace")) for p in scopes)
            ):
                continue
            result = (
                matcher.sub(lambda _match, replacement=new: replacement, result)
                if matcher
                else result.replace(old, new)
            )
        return result

    def detects(self, data, path=None):
        for old, _, scopes, _, matcher in self.rules:
            if scopes and (
                path is None or not any(p.search(path.decode("utf-8", "replace")) for p in scopes)
            ):
                continue
            if matcher.search(data) if matcher else old in data:
                return True
        return False


def tree_manifest(repo, ref, transform=None, blob_cache=None):
    result = {}
    for record in git(repo, "ls-tree", "-r", "-z", ref).split(b"\0"):
        if not record:
            continue
        meta, path = record.split(b"\t", 1)
        mode, kind, sha = meta.split()
        if transform and transform.removed(path):
            continue
        target = transform.filename(path) if transform else path
        if target in result:
            raise StopCleanup("Filename rewrite would collide with another file")
        if transform and kind == b"blob":
            key = (sha, path)
            if blob_cache is not None and key in blob_cache:
                sha = blob_cache[key]
            else:
                original = git(repo, "cat-file", "blob", sha.decode())
                modified = transform.content(original, path)
                if modified != original:
                    sha = git(repo, "hash-object", "--stdin", data=modified).strip()
                if blob_cache is not None:
                    blob_cache[key] = sha
        result[target] = (mode, kind, sha)
    return result


def commit_records(repo):
    commits = git(repo, "rev-list", "--all").decode().splitlines()
    result = {}
    for sha in commits:
        raw = git(repo, "cat-file", "commit", sha)
        headers, _, message = raw.partition(b"\n\n")
        authors = [
            line
            for line in headers.splitlines()
            if line.startswith((b"author ", b"committer ", b"encoding "))
        ]
        parents = [
            line.split()[1].decode() for line in headers.splitlines() if line.startswith(b"parent ")
        ]
        tree = next(
            line.split()[1].decode() for line in headers.splitlines() if line.startswith(b"tree ")
        )
        result[sha] = {"identities": authors, "parents": parents, "message": message, "tree": tree}
    return result


def expected_commit_trees(repo, records, transform, blob_cache):
    by_tree = {}
    by_commit = {}
    for sha, record in records.items():
        tree = record["tree"]
        if tree not in by_tree:
            original = tree_manifest(repo, tree)
            expected = tree_manifest(repo, tree, transform, blob_cache)
            by_tree[tree] = (expected, tree if original == expected else None)
        by_commit[sha] = by_tree[tree]
    return by_commit


def filter_worker(repo, config):
    if importlib.metadata.version("git-filter-repo") != VERSION:
        raise StopCleanup("Unexpected git-filter-repo version")
    import git_filter_repo as filtering

    transform = Transform(repo, config)
    os.chdir(repo)
    cache = {}

    def file_info(filename, mode, blob_id, value):
        if transform.removed(filename):
            return None, mode, blob_id
        if mode == b"160000":
            return filename, mode, blob_id
        key = (filename, blob_id)
        if key not in cache:
            raw = value.get_contents_by_identifier(blob_id)
            if raw is None:
                raise StopCleanup("Unable to read a historical blob")
            modified = transform.content(raw, filename)
            cache[key] = value.insert_file_with_contents(modified) if modified != raw else blob_id
        return filename, mode, cache[key]

    def commit_callback(commit, _metadata):
        changes = {}
        for change in commit.file_changes:
            original = change.filename
            if transform.removed(original):
                continue
            change.filename = transform.filename(original)
            previous = changes.get(change.filename)
            if previous:
                if (
                    previous.type == b"M"
                    and change.type == b"M"
                    and previous.blob_id != change.blob_id
                ):
                    raise StopCleanup("Historical path collision")
                if previous.type == b"M" and change.type == b"D":
                    continue
            changes[change.filename] = change
        commit.file_changes = list(changes.values())

    args = filtering.FilteringOptions.parse_args(
        [
            "--force",
            "--sensitive-data-removal",
            "--no-fetch",
            "--prune-empty",
            "never",
            "--prune-degenerate",
            "never",
            "--preserve-commit-hashes",
            "--preserve-commit-encoding",
            "--replace-refs",
            "delete-no-add",
            "--quiet",
        ]
    )
    filtering.RepoFilter(
        args,
        file_info_callback=file_info,
        commit_callback=commit_callback,
        message_callback=lambda message: transform.content(message),
    ).run()


def validate(repo, before_refs, before_commits, expected_trees, transform, expected_commits):
    after_refs = refs(repo)
    if set(after_refs) != set(before_refs):
        raise StopCleanup("Rewrite changed the set of refs")
    for name, expected in expected_trees.items():
        if tree_manifest(repo, name) != expected:
            raise StopCleanup("Rewritten tip differs from intended preserved files")
    map_file = Path(repo) / "filter-repo" / "commit-map"
    pairs = [line.split() for line in map_file.read_text().splitlines()[1:] if line.strip()]
    mapping = {old: new for old, new in pairs}
    if any(mapping.get(old, "0" * 40) == "0" * 40 for old in before_commits):
        raise StopCleanup("Rewrite removed a commit")
    if len({mapping[old] for old in before_commits}) != len(before_commits):
        raise StopCleanup("Rewrite collapsed distinct commits")
    after_commits = commit_records(repo)
    if len(after_commits) != len(before_commits):
        raise StopCleanup("Commit count changed")
    tree_cache = {}
    for old, record in before_commits.items():
        updated = after_commits[mapping[old]]
        if updated["parents"] != [mapping[parent] for parent in record["parents"]]:
            raise StopCleanup("Commit graph changed")
        if updated["identities"] != record["identities"]:
            raise StopCleanup("Author, committer, date or encoding changed")
        if updated["message"] != transform.content(record["message"]):
            raise StopCleanup("Unexpected commit message change")
        expected, clean_tree = expected_commits[old]
        if clean_tree and updated["tree"] != clean_tree:
            raise StopCleanup("A clean historical tree changed")
        if updated["tree"] not in tree_cache:
            tree_cache[updated["tree"]] = tree_manifest(repo, updated["tree"])
        if tree_cache[updated["tree"]] != expected:
            raise StopCleanup("Historical tree differs from the intended transformation")
    # Scan all reachable object content and all tree filenames, including root commits and PR refs.
    scanned = set()
    for commit in after_commits:
        for record in git(repo, "ls-tree", "-r", "-z", commit).split(b"\0"):
            if not record:
                continue
            metadata, path = record.split(b"\t", 1)
            _mode, kind, sha = metadata.split()
            if transform.removed(path):
                raise StopCleanup("Removed historical path remains reachable")
            if transform.detects(path):
                raise StopCleanup("Sensitive filename remains reachable")
            if kind == b"blob" and (sha, path) not in scanned:
                scanned.add((sha, path))
                if transform.detects(git(repo, "cat-file", "blob", sha.decode()), path):
                    raise StopCleanup("Sensitive value remains reachable")
    for sha in after_refs.values():
        if git(repo, "cat-file", "-t", sha).strip() == b"tag" and transform.detects(
            git(repo, "cat-file", "tag", sha)
        ):
            raise StopCleanup("Sensitive tag message remains reachable")
    return after_refs, mapping, len(scanned)


def push_command(remote, before, after):
    if set(before) != set(after):
        raise StopCleanup("Publishing cannot add or delete branch/tag refs")
    args = ["git", "push", "--atomic", "--porcelain"]
    args.extend("--force-with-lease=" + name + ":" + before[name] for name in sorted(before))
    args.append(remote)
    args.extend(after[name] + ":" + name for name in sorted(after))
    return args


def auth_environment(repository, publish):
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    token = env.get("GITHUB_TOKEN")
    if publish and (
        env.get("GITHUB_ACTIONS") != "true"
        or env.get("GITHUB_REPOSITORY") != repository
        or not token
    ):
        raise StopCleanup("Publishing requires the matching repository GitHub Actions token")
    if token:
        if env.get("GITHUB_REPOSITORY") != repository:
            raise StopCleanup("Token repository does not match configuration")
        auth = base64.b64encode(("x-access-token:" + token).encode()).decode()
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
        env["GIT_CONFIG_VALUE_0"] = "AUTHORIZATION: basic " + auth
    return env


def check_request(repo, config, trigger_ref, trigger_sha, observed):
    if (
        trigger_ref != config["target_ref"]
        or trigger_ref not in observed
        or observed[trigger_ref] != trigger_sha
    ):
        raise StopCleanup("Trigger is not the current configured branch head")
    request = json.loads(git(repo, "show", trigger_sha + ":" + REQUEST_PATH))
    if request.get("schema_version") != 1 or request.get("repository") != config["repository"]:
        raise StopCleanup("Cleanup request repository/schema mismatch")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", request.get("request_id", "")):
        raise StopCleanup("Invalid request ID")
    expected = request["expected_refs"]
    if set(expected) != set(observed) or any(
        not re.fullmatch(r"[0-9a-f]{40}", sha) for sha in expected.values()
    ):
        raise StopCleanup("Cleanup request does not cover every branch/tag")
    parents = git(repo, "rev-list", "--parents", "-n", "1", trigger_sha).decode().split()
    if parents != [trigger_sha, expected[trigger_ref]]:
        raise StopCleanup("Trigger is not the single child of the observed base")
    changed = git(
        repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", trigger_sha
    ).split(b"\0")
    if [path for path in changed if path] != [REQUEST_PATH.encode()]:
        raise StopCleanup("Trigger commit must only add or change the cleanup request")
    effective = dict(expected)
    effective[trigger_ref] = trigger_sha
    if observed != effective:
        raise StopCleanup("A branch or tag changed after request preparation")
    return request, effective


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--trigger-ref", default=os.environ.get("GITHUB_REF"))
    parser.add_argument("--trigger-sha", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--local-source", help="Local-only test source; publishing is prohibited")
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--filter-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = json.loads(config_path.read_text())
    if args.filter_worker:
        filter_worker(Path(args.workdir).resolve(), config)
        return 0
    if config.get("schema_version") != 1 or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", config.get("repository", "")
    ):
        raise StopCleanup("Invalid cleanup configuration")
    if args.publish and args.local_source:
        raise StopCleanup("Local test mode cannot publish")
    env = auth_environment(config["repository"], args.publish)
    remote = (
        str(Path(args.local_source).resolve())
        if args.local_source
        else "https://github.com/" + config["repository"] + ".git"
    )
    before_remote = remote_refs(remote, env)
    observed = public_refs(before_remote)
    workdir = Path(args.workdir).resolve()
    if workdir.exists():
        raise StopCleanup("Work directory must be new for a fresh mirror")
    workdir.parent.mkdir(parents=True, exist_ok=True)
    old_umask = os.umask(0o077)
    try:
        command(
            ["git", "clone", "--mirror", "--no-hardlinks", remote, str(workdir)],
            env=env,
            stage="fresh-mirror-clone",
        )
    finally:
        os.umask(old_umask)
    before_refs = refs(workdir)
    if public_refs(before_refs) != observed or remote_refs(remote, env) != before_remote:
        raise StopCleanup("Remote changed during clone")
    # A mirror fetches advertised refs/pull as well; fail if any advertised ref was omitted.
    if any(before_refs.get(name) != sha for name, sha in before_remote.items()):
        raise StopCleanup("Fresh mirror is missing advertised refs")
    request, effective = check_request(
        workdir, config, args.trigger_ref, args.trigger_sha, observed
    )
    transform = Transform(workdir, config)
    if any(transform.detects(name.encode()) for name in before_refs):
        raise StopCleanup("Sensitive ref name requires separate review")
    blob_cache = {}
    expected_trees = {
        name: tree_manifest(workdir, name, transform, blob_cache)
        for name in public_refs(before_refs)
    }
    clean_tips = [
        name
        for name, expected in expected_trees.items()
        if tree_manifest(workdir, name) == expected
    ]
    before_commits = commit_records(workdir)
    expected_commits = expected_commit_trees(workdir, before_commits, transform, blob_cache)
    command(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--filter-worker",
            "--config",
            str(config_path),
            "--workdir",
            str(workdir),
        ],
        env=env,
        stage="filter-repo",
    )
    after_refs, mapping, checked = validate(
        workdir, before_refs, before_commits, expected_trees, transform, expected_commits
    )
    after_public = public_refs(after_refs)
    first_file = workdir / "filter-repo" / "first-changed-commits"
    first_changes = [
        line.split()[0] for line in first_file.read_text().splitlines() if line.strip()
    ]
    readonly = [
        safe_ref(name)
        for name in before_refs
        if name not in observed and before_refs[name] != after_refs[name]
    ]
    report = {
        "repository": config["repository"],
        "request_id": request["request_id"],
        "mode": "validated-local-rewrite",
        "commits_preserved": len(before_commits),
        "all_commit_trees_verified": len(expected_commits),
        "rewritten_commits": sum(old != new for old, new in mapping.items()),
        "branch_tag_count": len(observed),
        "clean_tip_trees_preserved": len(clean_tips),
        "checked_blob_paths": checked,
        "first_changed_commits": first_changes,
        "read_only_refs_affected": readonly,
        "read_only_refs_not_pushed": sorted(
            safe_ref(name) for name in before_refs if name not in observed
        ),
        "notes": [
            "No branches/tags deleted; PR/internal refs are not pushed.",
            "Commit/tag signatures cannot survive a history rewrite. "
            "Authors, committers, dates and parent graph verified.",
            "GitHub cached views, PR refs and other clones/forks may retain old objects; "
            "GitHub Support cleanup may be required.",
        ],
    }
    if args.publish:
        if public_refs(remote_refs(remote, env)) != effective:
            raise StopCleanup("Remote branch/tag changed before atomic publish")
        command(
            push_command(remote, effective, after_public),
            cwd=workdir,
            env=env,
            stage="atomic-leased-push",
        )
        if public_refs(remote_refs(remote, env)) != after_public:
            raise StopCleanup(
                "Post-push refs differ; cleanup may be incomplete due to concurrent activity"
            )
        report["mode"] = "published-and-ref-verified"
    output = workdir.parent / (workdir.name + "-report.json")
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(
                "## Sensitive history cleanup\n\n```json\n"
                + json.dumps(report, indent=2)
                + "\n```\n"
            )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except StopCleanup as exc:
        print(
            json.dumps({"status": "stopped", "reason": str(exc), "sensitive_values_logged": False})
        )
        sys.exit(1)
    except Exception:
        print(
            json.dumps(
                {
                    "status": "stopped",
                    "reason": "Unexpected validation error; no source values printed.",
                    "sensitive_values_logged": False,
                }
            )
        )
        sys.exit(1)
