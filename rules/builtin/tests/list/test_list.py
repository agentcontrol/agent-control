"""Tests for list rule."""

import pytest
from pydantic import ValidationError

from agent_control_rules.list import ListRule, ListRuleConfig


class TestListRuleConfig:
    """Tests for list rule config validation."""

    def test_empty_string_value_rejected(self) -> None:
        """Test that empty-string list entries are rejected at config validation time."""
        # Given: a list rule config with an empty-string value
        # When: constructing the config model
        with pytest.raises(
            ValidationError, match="values must not contain empty or whitespace-only strings"
        ):
            ListRuleConfig(values=[""])
        # Then: validation rejects the config (asserted by pytest)

    def test_whitespace_only_value_rejected(self) -> None:
        """Test that whitespace-only list entries are rejected at config validation time."""
        # Given: a list rule config with a whitespace-only value
        # When: constructing the config model
        with pytest.raises(
            ValidationError, match="values must not contain empty or whitespace-only strings"
        ):
            ListRuleConfig(values=[" "])
        # Then: validation rejects the config (asserted by pytest)


class TestListRule:
    """Tests for list rule runtime behavior."""

    @pytest.mark.asyncio
    async def test_starts_with_matches_prefix(self) -> None:
        """Test that starts_with mode triggers on prefix matches."""
        # Given: a starts_with rule config
        rule = ListRule(
            ListRuleConfig(
                values=["/home/lev/agent-control", "/tmp/cache"],
                logic="any",
                match_on="match",
                match_mode="starts_with",
                case_sensitive=True,
            )
        )

        # When: evaluating a path under an allowed prefix
        result = await rule.evaluate("/home/lev/agent-control/server/src/app.py")

        # Then: the prefix match triggers
        assert result.matched is True
        assert result.metadata["matches"] == ["/home/lev/agent-control/server/src/app.py"]

    @pytest.mark.asyncio
    async def test_starts_with_matches_exact_path_value(self) -> None:
        """Test that starts_with mode matches the configured path value exactly."""
        # Given: a starts_with rule config
        rule = ListRule(
            ListRuleConfig(
                values=["/home/lev/agent-control"],
                logic="any",
                match_on="match",
                match_mode="starts_with",
                case_sensitive=True,
            )
        )

        # When: evaluating the exact configured path
        result = await rule.evaluate("/home/lev/agent-control")

        # Then: the exact path matches
        assert result.matched is True
        assert result.metadata["matches"] == ["/home/lev/agent-control"]

    @pytest.mark.asyncio
    async def test_starts_with_no_match_when_prefix_absent(self) -> None:
        """Test that starts_with mode does not trigger when no prefix matches."""
        # Given: a starts_with rule config
        rule = ListRule(
            ListRuleConfig(
                values=["/home/lev/agent-control", "/tmp/cache"],
                logic="any",
                match_on="match",
                match_mode="starts_with",
                case_sensitive=True,
            )
        )

        # When: evaluating a path with no configured prefix
        result = await rule.evaluate("/var/log/system.log")

        # Then: the rule does not trigger
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_starts_with_uses_raw_string_prefix_for_path_like_values(self) -> None:
        """Test that starts_with is generic string-prefix matching, not path-segment aware."""
        # Given: a starts_with rule configured with a path-like prefix
        rule = ListRule(
            ListRuleConfig(
                values=["/home/lev/agent-control"],
                logic="any",
                match_on="match",
                match_mode="starts_with",
                case_sensitive=True,
            )
        )

        # When: evaluating a sibling path that shares the same string prefix
        result = await rule.evaluate("/home/lev/agent-control-old/server")

        # Then: the rule matches because starts_with is not path-boundary aware
        assert result.matched is True
        assert result.metadata["matches"] == ["/home/lev/agent-control-old/server"]

    @pytest.mark.asyncio
    async def test_starts_with_honors_case_sensitivity(self) -> None:
        """Test that starts_with mode respects case sensitivity settings."""
        # Given: two starts_with rules that differ only by case sensitivity
        insensitive = ListRule(
            ListRuleConfig(
                values=["/HOME/LEV/AGENT-CONTROL"],
                logic="any",
                match_on="match",
                match_mode="starts_with",
                case_sensitive=False,
            )
        )
        sensitive = ListRule(
            ListRuleConfig(
                values=["/HOME/LEV/AGENT-CONTROL"],
                logic="any",
                match_on="match",
                match_mode="starts_with",
                case_sensitive=True,
            )
        )

        # When: evaluating the same lower-case path against both
        insensitive_result = await insensitive.evaluate("/home/lev/agent-control/server")
        sensitive_result = await sensitive.evaluate("/home/lev/agent-control/server")

        # Then: only the case-insensitive rule matches
        assert insensitive_result.matched is True
        assert sensitive_result.matched is False

    @pytest.mark.asyncio
    async def test_starts_with_supports_no_match_allowlists(self) -> None:
        """Test that starts_with works with no_match for allowlist-style controls."""
        # Given: a starts_with rule configured as an allowlist
        rule = ListRule(
            ListRuleConfig(
                values=["/home/lev/agent-control", "/tmp/cache"],
                logic="any",
                match_on="no_match",
                match_mode="starts_with",
                case_sensitive=True,
            )
        )

        # When: evaluating one allowed and one disallowed path
        allowed_result = await rule.evaluate("/home/lev/agent-control/server")
        denied_result = await rule.evaluate("/var/log/system.log")

        # Then: only the disallowed path triggers the control
        assert allowed_result.matched is False
        assert denied_result.matched is True

    @pytest.mark.asyncio
    async def test_starts_with_matches_plain_text_prefix(self) -> None:
        """Test that starts_with mode works for ordinary non-path strings."""
        # Given: a starts_with rule config for ordinary strings
        rule = ListRule(
            ListRuleConfig(
                values=["agent", "control:"],
                logic="any",
                match_on="match",
                match_mode="starts_with",
                case_sensitive=True,
            )
        )

        # When: evaluating values with and without the configured prefixes
        matched_result = await rule.evaluate("agent-control")
        unmatched_result = await rule.evaluate("please control: now")

        # Then: only the true prefix match triggers
        assert matched_result.matched is True
        assert unmatched_result.matched is False

    @pytest.mark.asyncio
    async def test_starts_with_escapes_regex_metacharacters(self) -> None:
        """Test that starts_with treats configured values as literals, not regex."""
        # Given: prefixes containing regex metacharacters
        rule = ListRule(
            ListRuleConfig(
                values=["release/v1.2+", "[beta]"],
                logic="any",
                match_on="match",
                match_mode="starts_with",
                case_sensitive=True,
            )
        )

        # When: evaluating values that begin with those literal prefixes
        release_result = await rule.evaluate("release/v1.2+rc1")
        beta_result = await rule.evaluate("[beta] feature flag")

        # Then: both values match literally
        assert release_result.matched is True
        assert beta_result.matched is True

    @pytest.mark.asyncio
    async def test_starts_with_supports_list_input_with_any_logic(self) -> None:
        """Test that starts_with works on list inputs when any item matches."""
        # Given: a starts_with rule with any-item semantics
        rule = ListRule(
            ListRuleConfig(
                values=["/home/lev/agent-control", "agent"],
                logic="any",
                match_on="match",
                match_mode="starts_with",
                case_sensitive=True,
            )
        )

        # When: evaluating a list where only one element matches
        result = await rule.evaluate(["/var/log/system.log", "agent-control"])

        # Then: the rule triggers and reports the matching entry
        assert result.matched is True
        assert result.metadata["matches"] == ["agent-control"]

    @pytest.mark.asyncio
    async def test_starts_with_supports_list_input_with_all_logic(self) -> None:
        """Test that starts_with respects all-item semantics for list inputs."""
        # Given: a starts_with rule with all-item semantics
        rule = ListRule(
            ListRuleConfig(
                values=["/home/lev/agent-control", "/tmp/cache"],
                logic="all",
                match_on="match",
                match_mode="starts_with",
                case_sensitive=True,
            )
        )

        # When: evaluating one fully matching list and one partially matching list
        matching_result = await rule.evaluate(
            ["/home/lev/agent-control/server", "/tmp/cache/build"]
        )
        partial_result = await rule.evaluate(
            ["/home/lev/agent-control/server", "/var/log/system.log"]
        )

        # Then: only the fully matching list triggers
        assert matching_result.matched is True
        assert partial_result.matched is False

    @pytest.mark.asyncio
    async def test_ends_with_matches_suffix(self) -> None:
        """Test that ends_with mode triggers on suffix matches."""
        # Given: an ends_with rule config
        rule = ListRule(
            ListRuleConfig(
                values=["/SOUL.md", ".py"],
                logic="any",
                match_on="match",
                match_mode="ends_with",
                case_sensitive=True,
            )
        )

        # When: evaluating a path with an allowed suffix
        result = await rule.evaluate("/home/lev/agent-control/SOUL.md")

        # Then: the suffix match triggers
        assert result.matched is True
        assert result.metadata["matches"] == ["/home/lev/agent-control/SOUL.md"]

    @pytest.mark.asyncio
    async def test_ends_with_matches_exact_path_value(self) -> None:
        """Test that ends_with mode matches the configured path value exactly."""
        # Given: an ends_with rule config
        rule = ListRule(
            ListRuleConfig(
                values=["/home/lev/agent-control/SOUL.md"],
                logic="any",
                match_on="match",
                match_mode="ends_with",
                case_sensitive=True,
            )
        )

        # When: evaluating the exact configured path
        result = await rule.evaluate("/home/lev/agent-control/SOUL.md")

        # Then: the exact path matches
        assert result.matched is True
        assert result.metadata["matches"] == ["/home/lev/agent-control/SOUL.md"]

    @pytest.mark.asyncio
    async def test_ends_with_no_match_when_suffix_absent(self) -> None:
        """Test that ends_with mode does not trigger when no suffix matches."""
        # Given: an ends_with rule config
        rule = ListRule(
            ListRuleConfig(
                values=["/SOUL.md", ".py"],
                logic="any",
                match_on="match",
                match_mode="ends_with",
                case_sensitive=True,
            )
        )

        # When: evaluating a path with no configured suffix
        result = await rule.evaluate("/var/log/system.log")

        # Then: the rule does not trigger
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_ends_with_honors_case_sensitivity(self) -> None:
        """Test that ends_with mode respects case sensitivity settings."""
        # Given: two ends_with rules that differ only by case sensitivity
        insensitive = ListRule(
            ListRuleConfig(
                values=["/SOUL.MD"],
                logic="any",
                match_on="match",
                match_mode="ends_with",
                case_sensitive=False,
            )
        )
        sensitive = ListRule(
            ListRuleConfig(
                values=["/SOUL.MD"],
                logic="any",
                match_on="match",
                match_mode="ends_with",
                case_sensitive=True,
            )
        )

        # When: evaluating the same lower-case path against both
        insensitive_result = await insensitive.evaluate("/home/lev/agent-control/SOUL.md")
        sensitive_result = await sensitive.evaluate("/home/lev/agent-control/SOUL.md")

        # Then: only the case-insensitive rule matches
        assert insensitive_result.matched is True
        assert sensitive_result.matched is False

    @pytest.mark.asyncio
    async def test_ends_with_supports_no_match_allowlists(self) -> None:
        """Test that ends_with works with no_match for allowlist-style controls."""
        # Given: an ends_with rule configured as an allowlist
        rule = ListRule(
            ListRuleConfig(
                values=[".md", ".txt"],
                logic="any",
                match_on="no_match",
                match_mode="ends_with",
                case_sensitive=True,
            )
        )

        # When: evaluating one allowed and one disallowed path
        allowed_result = await rule.evaluate("/home/lev/agent-control/SOUL.md")
        denied_result = await rule.evaluate("/var/log/system.log")

        # Then: only the disallowed path triggers the control
        assert allowed_result.matched is False
        assert denied_result.matched is True

    @pytest.mark.asyncio
    async def test_ends_with_matches_plain_text_suffix(self) -> None:
        """Test that ends_with mode works for ordinary non-path strings."""
        # Given: an ends_with rule config for ordinary strings
        rule = ListRule(
            ListRuleConfig(
                values=["-control", ":done"],
                logic="any",
                match_on="match",
                match_mode="ends_with",
                case_sensitive=True,
            )
        )

        # When: evaluating values with and without the configured suffixes
        matched_result = await rule.evaluate("agent-control")
        unmatched_result = await rule.evaluate("done: please")

        # Then: only the true suffix match triggers
        assert matched_result.matched is True
        assert unmatched_result.matched is False

    @pytest.mark.asyncio
    async def test_ends_with_escapes_regex_metacharacters(self) -> None:
        """Test that ends_with treats configured values as literals, not regex."""
        # Given: suffixes containing regex metacharacters
        rule = ListRule(
            ListRuleConfig(
                values=[".tar.gz+", "[beta]"],
                logic="any",
                match_on="match",
                match_mode="ends_with",
                case_sensitive=True,
            )
        )

        # When: evaluating values that end with those literal suffixes
        archive_result = await rule.evaluate("release-1.tar.gz+")
        beta_result = await rule.evaluate("feature-[beta]")

        # Then: both values match literally
        assert archive_result.matched is True
        assert beta_result.matched is True

    @pytest.mark.asyncio
    async def test_ends_with_supports_list_input_with_any_logic(self) -> None:
        """Test that ends_with works on list inputs when any item matches."""
        # Given: an ends_with rule with any-item semantics
        rule = ListRule(
            ListRuleConfig(
                values=[".md", "-control"],
                logic="any",
                match_on="match",
                match_mode="ends_with",
                case_sensitive=True,
            )
        )

        # When: evaluating a list where only one element matches
        result = await rule.evaluate(["/var/log/system.log", "agent-control"])

        # Then: the rule triggers and reports the matching entry
        assert result.matched is True
        assert result.metadata["matches"] == ["agent-control"]

    @pytest.mark.asyncio
    async def test_ends_with_supports_list_input_with_all_logic(self) -> None:
        """Test that ends_with respects all-item semantics for list inputs."""
        # Given: an ends_with rule with all-item semantics
        rule = ListRule(
            ListRuleConfig(
                values=[".md", ".txt"],
                logic="all",
                match_on="match",
                match_mode="ends_with",
                case_sensitive=True,
            )
        )

        # When: evaluating one fully matching list and one partially matching list
        matching_result = await rule.evaluate(
            ["/home/lev/agent-control/SOUL.md", "/tmp/cache/notes.txt"]
        )
        partial_result = await rule.evaluate(
            ["/home/lev/agent-control/SOUL.md", "/var/log/system.log"]
        )

        # Then: only the fully matching list triggers
        assert matching_result.matched is True
        assert partial_result.matched is False

    @pytest.mark.asyncio
    async def test_legacy_empty_string_value_is_ignored_defensively(self) -> None:
        """Test that legacy invalid configs do not compile into a match-all regex."""
        # Given: a legacy invalid config constructed without validation
        config = ListRuleConfig.model_construct(
            values=[""],
            logic="any",
            match_on="match",
            match_mode="contains",
            case_sensitive=False,
        )
        rule = ListRule(config)

        # When: evaluating normal text against the legacy config
        result = await rule.evaluate("Tell me a joke")

        # Then: the rule ignores the empty control values
        assert result.matched is False
        assert result.message == "Empty control values - control ignored"

    @pytest.mark.asyncio
    async def test_legacy_whitespace_only_value_is_ignored_defensively(self) -> None:
        """Test that legacy whitespace-only configs do not compile into pathological regexes."""
        # Given: a legacy invalid config with a whitespace-only value
        config = ListRuleConfig.model_construct(
            values=[" "],
            logic="any",
            match_on="match",
            match_mode="contains",
            case_sensitive=False,
        )
        rule = ListRule(config)

        # When: evaluating normal text against the legacy config
        result = await rule.evaluate("Tell me a joke")

        # Then: the rule ignores the empty control values
        assert result.matched is False
        assert result.message == "Empty control values - control ignored"

    @pytest.mark.asyncio
    async def test_legacy_empty_string_allowlist_does_not_block_all(self) -> None:
        """Test that legacy invalid allowlist configs do not block all inputs."""
        # Given: a legacy invalid allowlist config constructed without validation
        config = ListRuleConfig.model_construct(
            values=[""],
            logic="any",
            match_on="no_match",
            match_mode="contains",
            case_sensitive=False,
        )
        rule = ListRule(config)

        # When: evaluating normal text against the legacy config
        result = await rule.evaluate("legitimate_value")

        # Then: the rule ignores the empty control values instead of blocking all input
        assert result.matched is False
        assert result.message == "Empty control values - control ignored"
