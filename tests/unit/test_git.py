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

    def __call__(self, argv, cwd):
        key = tuple(argv[1:])
        return self.responses.get(key, Output("", returncode=1))


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


if __name__ == "__main__":
    unittest.main()
