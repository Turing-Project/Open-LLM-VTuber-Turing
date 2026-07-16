import unittest

from src.open_llm_vtuber.utils.tts_preprocessor import StreamingReasoningMarkupFilter


class ReasoningMarkupFilterTests(unittest.TestCase):
    def test_filters_square_bracket_thinking_until_visible_state(self):
        text = (
            "[thinking]\n\n哦，[thinking]\n\n"
            "The player is looking at a GitHub repository page for "
            '"Open-LLM-VTuber-Turing" - it\'s not a game, it is a code repository.'
            "[neutral] 哦？在看Open-LLM-VTuber的GitHub仓库呢。"
        )

        filter_ = StreamingReasoningMarkupFilter()
        result = "".join(filter_.feed(chunk) for chunk in [text[:8], text[8:25], text[25:]])
        result += filter_.flush()

        self.assertEqual(result.strip(), "哦？在看Open-LLM-VTuber的GitHub仓库呢。")

    def test_filters_angle_think_tags_across_chunks(self):
        filter_ = StreamingReasoningMarkupFilter()
        result = ""
        for chunk in ["<thi", "nk>hidden", "</th", "ink>最终回答"]:
            result += filter_.feed(chunk)
        result += filter_.flush()

        self.assertEqual(result, "最终回答")


if __name__ == "__main__":
    unittest.main()
