"""一時Gitリポジトリで、追跡範囲外のデプロイ対象も最新として判定する。"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import remote_commands as rc


def find_shell():
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            for directory in Path(git).parents:
                candidate = directory / "bin" / "bash.exe"
                if candidate.is_file():
                    return str(candidate)
    return shutil.which("sh")


class DeployFetchGitTests(unittest.TestCase):
    def setUp(self):
        self.shell = find_shell()
        if not self.shell or not shutil.which("git"):
            self.skipTest("GitとPOSIXシェルが必要です。")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.env = dict(os.environ)
        # 利用者のGit設定・署名・フック・SSH接続先をテストへ持ち込まない。
        for key in list(self.env):
            if key.startswith("GIT_"):
                self.env.pop(key)
        self.env.update(
            GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="Test", GIT_COMMITTER_NAME="Test",
            GIT_AUTHOR_EMAIL="test@example.invalid", GIT_COMMITTER_EMAIL="test@example.invalid",
            GIT_TERMINAL_PROMPT="0",
        )
        self.remote = self.root / "remote.git"
        self.seed = self.root / "seed"
        self.git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.git(self.root, "init", "--initial-branch=main", str(self.seed))
        self.git(self.seed, "commit", "--allow-empty", "-m", "初期状態")
        self.git(self.seed, "branch", "release/test")
        self.git(self.seed, "remote", "add", "origin", str(self.remote))
        self.git(self.seed, "push", "origin", "main", "release/test")
        self.old = self.git(self.seed, "rev-parse", "HEAD")

    def git(self, cwd, *args):
        return subprocess.run(
            ["git", *args], cwd=cwd, env=self.env, check=True,
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        ).stdout.strip()

    def command(self, command):
        return subprocess.run(
            [self.shell, "-c", command], env=self.env, check=True,
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        ).stdout.strip().splitlines()

    def clone(self, single):
        clone = self.root / ("single clone" if single else "normal clone")
        args = ["clone"]
        if single:
            args += ["--single-branch", "--branch", "main"]
        self.git(self.root, *args, str(self.remote), str(clone))
        self.git(clone, "checkout", "-b", "release/test", self.old)
        self.git(clone, "update-ref", "refs/remotes/origin/release/test", self.old)
        return clone

    def advance_remote(self):
        self.git(self.seed, "checkout", "release/test")
        self.git(self.seed, "commit", "--allow-empty", "-m", "リモートの更新")
        self.git(self.seed, "push", "origin", "release/test")
        return self.git(self.seed, "rev-parse", "HEAD")

    def test_normal_and_single_branch_clones_fetch_latest_and_merge_same_target(self):
        clones = [self.clone(single) for single in (False, True)]
        new = self.advance_remote()
        for clone in clones:
            with self.subTest(clone=clone.name):
                before_config = self.git(clone, "config", "--get-all", "remote.origin.fetch")
                target, behind, ahead = self.command(rc.deploy_fetch_command(clone.as_posix(), "release/test"))
                self.assertEqual((target, behind, ahead), (new, "1", "0"))
                self.assertEqual(self.git(clone, "rev-parse", "refs/remotes/origin/release/test"), new)
                self.assertEqual(self.git(clone, "config", "--get-all", "remote.origin.fetch"), before_config)
                merged = self.command(rc.deploy_merge_command(clone.as_posix(), "release/test"))
                self.assertEqual(merged[-1], new)
                self.assertEqual(self.command(rc.deploy_fetch_command(clone.as_posix(), "release/test")),
                                 [new, "0", "0"])

    def test_local_only_commits_and_divergence_remain_visible(self):
        clone = self.clone(True)
        self.git(clone, "commit", "--allow-empty", "-m", "サーバーだけの更新")
        self.assertEqual(self.command(rc.deploy_fetch_command(clone.as_posix(), "release/test")),
                         [self.old, "0", "1"])
        new = self.advance_remote()
        self.assertEqual(self.command(rc.deploy_fetch_command(clone.as_posix(), "release/test")),
                         [new, "1", "1"])

    def test_missing_tracking_ref_is_created_and_missing_branch_fails(self):
        clone = self.clone(True)
        self.git(clone, "update-ref", "-d", "refs/remotes/origin/release/test")
        new = self.advance_remote()
        self.assertEqual(self.command(rc.deploy_fetch_command(clone.as_posix(), "release/test")),
                         [new, "1", "0"])
        with self.assertRaises(subprocess.CalledProcessError):
            self.command(rc.deploy_fetch_command(clone.as_posix(), "missing"))
