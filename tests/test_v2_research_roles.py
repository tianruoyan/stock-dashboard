from __future__ import annotations

import unittest

from v2_platform.research import V2ResearchSystemBuilder


class ResearchRoleTests(unittest.TestCase):
    def test_roles_require_explicit_tag_or_topic_wording(self) -> None:
        roles, evidence = V2ResearchSystemBuilder._roles(["指数权重"], ["半导体设备平台", "零部件弹性"])
        self.assertEqual(set(roles), {"core", "platform", "high_beta"})
        self.assertTrue(all(evidence))

    def test_unclassified_is_retained_without_explicit_evidence(self) -> None:
        roles, evidence = V2ResearchSystemBuilder._roles(["半导体设备"], ["科技硬件链"])
        self.assertEqual(roles, ["unclassified"])
        self.assertIn("保持未分类", evidence[0])


if __name__ == "__main__":
    unittest.main()
