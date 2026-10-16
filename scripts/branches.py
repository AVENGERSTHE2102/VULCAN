"""Create control-snapshot branches without switching or disturbing the working tree."""

import subprocess


def git(*args, input=None):
    return subprocess.check_output(["git", *args], input=input, text=True).strip()


if __name__ == "__main__":
    if git("status", "--porcelain"):
        raise SystemExit(
            "Commit the verified implementation before creating distribution branches."
        )
    parent = git("rev-parse", "HEAD")
    for branch, mode in [("vulnerable", "vulnerable"), ("known-good", "hardened")]:
        exists = (
            subprocess.run(
                ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + branch]
            ).returncode
            == 0
        )
        if exists:
            raise SystemExit(f"{branch} already exists; refusing to replace it")
        blob = git("hash-object", "-w", "--stdin", input=mode + "\n")
        lines = git("ls-tree", parent).splitlines()
        lines = [line for line in lines if not line.endswith("\t.default-mode")]
        lines.append("100644 blob " + blob + "\t.default-mode")
        tree = git("mktree", input="\n".join(lines) + "\n")
        commit = git(
            "commit-tree", tree, "-p", parent, input=f"Start lab with {mode} controls\n"
        )
        git("update-ref", "refs/heads/" + branch, commit)
        assert git("show", branch + ":.default-mode") == mode
        assert git("diff", "--name-only", parent, branch) in ("", ".default-mode")
        print(branch, commit)
