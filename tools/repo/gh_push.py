#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gh_push.py - push through the GitHub REST API instead of git-over-https.

Why this exists
---------------
``git push`` needs a smart-HTTP session, which some networks, proxies and
corporate middleboxes break even when the host is reachable: the TCP connect
succeeds and the exchange then stalls.  The REST API is ordinary HTTPS
requests and works in those environments, so this script does the push over
it (blobs -> tree -> commit -> ref).

What it does
------------
Builds one commit whose tree is *exactly* the tree of the local HEAD, on top
of whatever the remote branch currently points at.  Nothing is guessed:

  * every blob is uploaded and its SHA is compared against ``git ls-tree``;
  * the assembled tree SHA must equal ``git rev-parse HEAD^{tree}``;
  * only then is the branch ref moved, and never with ``force``.

So if any file differs - including the executable bit, which is the easy one
to get wrong - the run stops before touching the ref.

Usage
-----
    export GH_TOKEN=github_pat_...
    python tools/gh_push.py --message-file /tmp/msg.txt
    python tools/gh_push.py -m "one line" --dry-run
    python tools/gh_push.py --branch main --repo <owner>/<repo>

The token is read from GH_TOKEN only.  It is never written to disk, never
embedded in the commit, and never sent anywhere but api.github.com.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"


def api(method, path, body=None, tries=5):
    url = API + path
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for i in range(tries):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer " + os.environ["GH_TOKEN"])
        req.add_header("Accept", "application/vnd.github+json")
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")[:400]
            last = "HTTP %d %s" % (e.code, text)
            # GitHub returns 400 for transient blob-upload rejections too;
            # seen when the requests come faster than a few per second.
            if e.code in (400, 403, 429, 500, 502, 503, 504):
                time.sleep(1.5 * (i + 1))
                continue
            raise SystemExit("%s %s -> %s" % (method, path, last))
        except Exception as e:                       # timeouts, resets
            last = repr(e)
            time.sleep(1.5 * (i + 1))
    raise SystemExit("%s %s failed after %d tries: %s" % (method, path, tries, last))


def local_tree(repo):
    """path -> (mode, blob_sha) for every tracked file."""
    out = subprocess.run(["git", "ls-tree", "-r", "HEAD"], cwd=repo,
                         capture_output=True, text=True, check=True).stdout
    res = {}
    for line in out.splitlines():
        meta, path = line.split("\t", 1)
        mode, _typ, sha = meta.split()
        res[path] = (mode, sha)
    return res


def head_tree_sha(repo):
    return subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=repo,
                          capture_output=True, text=True,
                          check=True).stdout.strip()


def guess_repo(repo: str) -> str:
    """owner/name, taken from remote.origin.url so nothing is hard-coded."""
    try:
        url = subprocess.run(["git", "config", "--get", "remote.origin.url"],
                             cwd=repo, capture_output=True, text=True,
                             check=True).stdout.strip()
    except subprocess.CalledProcessError:
        raise SystemExit("✗ --repo not given and there is no remote.origin.url")
    m = re.search(r"[/:]([^/:]+)/([^/]+?)(?:\.git)?/?$", url)
    if not m:
        raise SystemExit("✗ cannot parse owner/name out of %r, pass --repo" % url)
    return "%s/%s" % (m.group(1), m.group(2))


def main() -> int:
    ap = argparse.ArgumentParser(description="push via the GitHub REST API")
    ap.add_argument("--repo", help="owner/name, defaults to remote.origin.url")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--dir", default=".", help="local git work tree")
    ap.add_argument("-m", "--message", help="commit message")
    ap.add_argument("--message-file", help="read commit message from a file")
    ap.add_argument("--dry-run", action="store_true",
                    help="show the diff, upload nothing")
    ap.add_argument("--allow-delete", action="store_true",
                    help="allow paths present upstream but not locally to be removed")
    ap.add_argument("--orphan", action="store_true",
                    help="write a parentless commit and force the branch to it, "
                         "dropping upstream history (use when history itself "
                         "must not stay published)")
    ap.add_argument("--force", action="store_true",
                    help="move the ref even if the update is not a fast-forward")
    args = ap.parse_args()
    if not args.repo:
        args.repo = guess_repo(os.path.abspath(args.dir))

    if not os.environ.get("GH_TOKEN"):
        raise SystemExit("GH_TOKEN is not set")

    repo = os.path.abspath(args.dir)
    msg = args.message
    if args.message_file:
        with open(args.message_file, encoding="utf-8") as fh:
            msg = fh.read().rstrip() + "\n"
    if not msg:
        raise SystemExit("no commit message (-m or --message-file)")

    ref = api("GET", "/repos/%s/git/ref/heads/%s" % (args.repo, args.branch))
    base = ref["object"]["sha"]
    base_tree = api("GET", "/repos/%s/git/commits/%s" % (args.repo, base))["tree"]["sha"]
    print("remote %s @ %s  tree %s" % (args.branch, base[:8], base_tree[:8]))

    remote = {e["path"]: (e["mode"], e["sha"])
              for e in api("GET", "/repos/%s/git/trees/%s?recursive=1"
                           % (args.repo, base_tree))["tree"]
              if e["type"] == "blob"}
    local = local_tree(repo)

    if args.orphan:
        # No base tree to inherit from, so every blob has to go up again.
        added, changed, vanished = sorted(local), [], []
        print("orphan: uploading all %d blobs, the new commit has no parent"
              % len(added))
    else:
        added = sorted(set(local) - set(remote))
        changed = sorted(p for p in set(local) & set(remote) if local[p][1] != remote[p][1])
        vanished = sorted(set(remote) - set(local))

    print("remote %d blobs, local %d blobs" % (len(remote), len(local)))
    for p in added:
        print("   + %s" % p)
    for p in changed:
        print("   ~ %s" % p)
    if vanished:
        # 重组目录时必然有删除（旧路径、废弃模块）。默认拒绝，--allow-delete 才删。
        if not args.allow_delete:
            print("\n! these exist upstream but not locally, refusing:")
            for p in vanished:
                print("   - %s" % p)
            print("\n  （确认这些是真该删的，加 --allow-delete 重跑）")
            return 1
        print("\n- deleting %d paths upstream (--allow-delete):" % len(vanished))
        for p in vanished:
            print("   - %s" % p)
    if not added and not changed and not vanished:
        print("\nnothing to push, trees already match")
        return 0
    print("\n%d added, %d changed, %d deleted"
          % (len(added), len(changed), len(vanished)))

    if args.dry_run:
        print("[dry-run] nothing uploaded")
        return 0

    entries = []
    for p in added + changed:
        with open(os.path.join(repo, p), "rb") as fh:
            raw = fh.read()
        b = api("POST", "/repos/%s/git/blobs" % args.repo,
                {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
        mode, want = local[p]
        if b["sha"] != want:
            print("! blob mismatch for %s: api=%s local=%s"
                  % (p, b["sha"][:8], want[:8]))
            return 2
        entries.append({"path": p, "mode": mode, "type": "blob", "sha": b["sha"]})
        print("  %s  %s  %s" % (b["sha"][:8], mode, p))
        time.sleep(0.4)

    # 删除：tree API 里把 sha 置 null 就是从 base_tree 上摘掉这个路径。
    if vanished and args.allow_delete:
        for p in vanished:
            entries.append({"path": p, "mode": remote[p][0], "type": "blob", "sha": None})

    tree_body = {"tree": entries}
    if not args.orphan:
        tree_body["base_tree"] = base_tree
    tree = api("POST", "/repos/%s/git/trees" % args.repo, tree_body)
    print("\nnew tree %s" % tree["sha"][:12])

    want_tree = head_tree_sha(repo)
    if tree["sha"] != want_tree:
        print("! new tree %s != HEAD tree %s" % (tree["sha"][:8], want_tree[:8]))
        print("  something differs (a mode bit?), ref not moved")
        return 3
    print("tree matches HEAD exactly")

    commit = api("POST", "/repos/%s/git/commits" % args.repo,
                 {"message": msg, "tree": tree["sha"],
                  "parents": [] if args.orphan else [base]})
    print("commit %s" % commit["sha"])

    api("PATCH", "/repos/%s/git/refs/heads/%s" % (args.repo, args.branch),
        {"sha": commit["sha"], "force": bool(args.force or args.orphan)})
    print("%s -> %s" % (args.branch, commit["sha"]))
    print("https://github.com/%s/commit/%s" % (args.repo, commit["sha"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
