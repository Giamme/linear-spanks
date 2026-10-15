from __future__ import annotations

from tests.contract_support import *


class CompositionAndMetadataTest(unittest.TestCase):
    def test_linear_workflow_is_a_bounded_router(self) -> None:
        workflow = ROOT / "skills" / "linear-workflow"
        router = (workflow / "SKILL.md").read_text(encoding="utf-8")

        self.assertLess(len(router.split()), 300)
        for reference in (
            "connector-contract.md",
            "task-lifecycle.md",
            "document-persistence.md",
        ):
            self.assertIn(f"references/{reference}", router)
            self.assertTrue((workflow / "references" / reference).is_file())

    def test_every_technology_skill_defers_to_repository_evidence(self) -> None:
        for skill in sorted((ROOT / "skills" / "extras").glob("tech-*")):
            with self.subTest(skill=skill.name):
                content = (skill / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn("repository conventions and supported versions", content)
                self.assertIn("record the reason in the implementation plan", content)

    def test_every_distributed_skill_has_ui_metadata(self) -> None:
        distributed: set[str] = set()
        for line in (ROOT / "skills-manifest.txt").read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            name, _group = line.split()
            distributed.add(name)
            core = ROOT / "skills" / name
            skill = core if core.is_dir() else ROOT / "skills" / "extras" / name
            metadata = skill / "agents" / "openai.yaml"
            with self.subTest(skill=name):
                self.assertTrue(metadata.is_file())
                content = metadata.read_text(encoding="utf-8")
                self.assertIn(f"$${name}".replace("$$", "$"), content)

        core = {
            path.name
            for path in (ROOT / "skills").iterdir()
            if path.is_dir() and path.name != "extras"
        }
        actual = core | {
            path.name for path in (ROOT / "skills" / "extras").iterdir() if path.is_dir()
        }
        self.assertEqual(distributed, actual)


class PreservedBehaviorTest(unittest.TestCase):
    def test_learning_templates_keep_required_fields(self) -> None:
        expected = {
            "project-learning-index.md": ("## Entry Registry", "## How Future Planners Use This"),
            "learning-entry.md": (
                "## Root Cause",
                "## Where This Does Not Apply",
                "## Source Evidence",
            ),
            "milestone-learning-index.md": (
                "## Approved Learning Entries",
                "## Retrospective Link",
            ),
        }
        for filename, phrases in expected.items():
            content = (SKILL / "templates" / filename).read_text(encoding="utf-8")
            for phrase in phrases:
                self.assertIn(phrase, content)

    def test_wrap_policy_requires_approval_readback_and_no_empty_entries(self) -> None:
        policy = (SKILL / "references" / "milestone-commands.md").read_text(encoding="utf-8")

        self.assertIn("Obtain approval before saving learning artifacts", policy)
        self.assertIn("read back each artifact", policy)
        self.assertIn("No reusable project learnings identified", policy)
        self.assertIn("do not create empty entries", policy)

    def test_project_epoch_templates_and_policy_preserve_release_boundaries(self) -> None:
        capsule_template = (SKILL / "templates" / "project-context-capsule.md").read_text(
            encoding="utf-8"
        )
        rollover_template = (SKILL / "templates" / "project-rollover-proposal.md").read_text(
            encoding="utf-8"
        )
        policy = (SKILL / "references" / "project-epoch.md").read_text(encoding="utf-8")

        for heading in PROJECT_EPOCH["capsule"]["required_headings"]:
            self.assertIn(heading, capsule_template)
        self.assertIn("three-to-seven outcome milestones", policy)
        self.assertIn("start each issue in `Unplanned`", policy)
        self.assertIn("source project to a Completed-category status", policy)
        self.assertIn("Project Rollover Receipt — <next release>", policy)
        self.assertIn(
            "must not begin mutation",
            (
                ROOT / "skills" / "linear-workflow" / "references" / "document-persistence.md"
            ).read_text(encoding="utf-8"),
        )
        self.assertIn("Do not create detailed tasks or plans here", rollover_template)
        self.assertEqual(PROJECT_EPOCH["capsule"]["max_body_bytes"], 24576)
        self.assertEqual(PROJECT_EPOCH["rollover"]["drift_result"], "ROLLOVER_DRIFT")

    def test_router_preserves_project_targeting_options(self) -> None:
        router = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        for option in (
            "--project <key-or-name>",
            "--project-id <linear-project-id>",
            "--team <key-or-name>",
            "--strict-project",
            "--include-cross-project-blockers",
        ):
            self.assertIn(option, router)
