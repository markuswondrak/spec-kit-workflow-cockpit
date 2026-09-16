import subprocess
import tempfile
import unittest
from pathlib import Path

from workflow_cockpit.services.git import GitService


class Output:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


class FakeRunner:
    def __init__(self, responses):
        self.responses = responses

    def __call__(self, argv, cwd, *, timeout=30.0):
        key = tuple(argv[1:])
        return self.responses.get(key, Output("", returncode=1))


class RaisingRunner:
    def __init__(self, error):
        self.error = error

    def __call__(self, argv, cwd, *, timeout=30.0):
        raise self.error


class GitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_head_branch_dirty(self):
        runner = FakeRunner(
            {
                ("rev-parse", "--is-inside-work-tree"): Output("true\n"),
                ("rev-parse", "HEAD"): Output("a" * 40 + "\n"),
                ("rev-parse", "--abbrev-ref", "HEAD"): Output("feature/x\n"),
                ("status", "--porcelain"): Output(" M file.txt\n"),
            }
        )
        service = GitService(self.root, runner=runner)
        self.assertTrue(service.is_worktree())
        self.assertEqual(service.head(), "a" * 40)
        self.assertEqual(service.branch(), "feature/x")
        self.assertTrue(service.is_dirty())

    def test_detached_head_has_no_branch(self):
        runner = FakeRunner(
            {
                ("rev-parse", "--abbrev-ref", "HEAD"): Output("HEAD\n"),
            }
        )
        self.assertIsNone(GitService(self.root, runner=runner).branch())

    def test_unborn_head_is_none(self):
        runner = FakeRunner({("rev-parse", "HEAD"): Output("", returncode=128)})
        self.assertIsNone(GitService(self.root, runner=runner).head())

    def test_branch_timeout_is_classified_not_raised(self):
        service = GitService(self.root, runner=RaisingRunner(subprocess.TimeoutExpired("git", 2.0)))
        result = service.branch_result()
        self.assertFalse(result.ok)
        self.assertIsNone(result.value)
        self.assertIn("timed out", result.error)

    def test_branch_oserror_is_classified_not_raised(self):
        service = GitService(self.root, runner=RaisingRunner(OSError("git missing")))
        result = service.branch_result()
        self.assertFalse(result.ok)
        self.assertIn("git missing", result.error)

    def test_branch_nonzero_status_is_a_normal_missing_branch(self):
        runner = FakeRunner({("rev-parse", "--abbrev-ref", "HEAD"): Output("", returncode=128)})
        result = GitService(self.root, runner=runner).branch_result()
        self.assertTrue(result.ok)
        self.assertIsNone(result.value)


if __name__ == "__main__":
    unittest.main()
