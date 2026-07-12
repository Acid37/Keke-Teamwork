"""Token 估算精度测试。

验证改进后的 _estimate_tokens 对 CJK 和 ASCII 字符的估算。
"""

import unittest

from backend.agent import Agent


class TokenEstimateTests(unittest.TestCase):
    def test_pure_ascii(self):
        """纯 ASCII 文本应按 ~4 char/token 估算。"""
        messages = [{"role": "user", "content": "a" * 100}]
        est = Agent._estimate_tokens(messages)
        self.assertEqual(est, 25)  # 100 / 4 = 25

    def test_pure_cjk(self):
        """纯 CJK 文本应按 ~1 char/token 估算。"""
        messages = [{"role": "user", "content": "你" * 100}]
        est = Agent._estimate_tokens(messages)
        self.assertEqual(est, 100)  # 100 CJK chars = 100 tokens

    def test_mixed_content(self):
        """混合 CJK + ASCII 应分别计算。"""
        # 50 CJK chars (50 tokens) + 40 ASCII chars (10 tokens) = 60
        content = "你" * 50 + "a" * 40
        messages = [{"role": "user", "content": content}]
        est = Agent._estimate_tokens(messages)
        self.assertEqual(est, 60)

    def test_empty_content(self):
        """空内容应返回 0。"""
        messages = [{"role": "user", "content": ""}]
        est = Agent._estimate_tokens(messages)
        self.assertEqual(est, 0)

    def test_none_content(self):
        """None 内容应按 0 处理。"""
        messages = [{"role": "user", "content": None}]
        est = Agent._estimate_tokens(messages)
        self.assertEqual(est, 0)

    def test_tool_calls_included(self):
        """tool_calls 字段应纳入估算。"""
        messages = [
            {"role": "assistant", "content": "ok", "tool_calls": [{"id": "1", "name": "read_file"}]},
        ]
        est = Agent._estimate_tokens(messages)
        # content "ok" = 2 ASCII = 0 tokens (2//4=0)
        # tool_calls JSON contains ASCII chars
        self.assertGreater(est, 0)

    def test_multiple_messages(self):
        """多条消息应累加。"""
        messages = [
            {"role": "user", "content": "你" * 10},   # 10
            {"role": "assistant", "content": "好" * 10},  # 10
        ]
        est = Agent._estimate_tokens(messages)
        self.assertEqual(est, 20)

    def test_cjk_better_than_chars_div_3(self):
        """对纯 CJK 文本，新估算应比 chars//3 更准确（更高）。"""
        content = "你好世界" * 100  # 400 CJK chars
        messages = [{"role": "user", "content": content}]
        est = Agent._estimate_tokens(messages)
        old_est = len(content) // 3  # 旧算法
        # 新算法 400 tokens vs 旧算法 133 tokens
        self.assertGreater(est, old_est)


if __name__ == "__main__":
    unittest.main()