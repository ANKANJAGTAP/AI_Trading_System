"""P1#12 — durable command state machine (pure): claim -> succeed/fail, with
bounded retries to DEAD_LETTER."""
from common.commands import (CLAIMED, CREATED, DEAD_LETTER, EXECUTING, RETRYING,
                             SUCCEEDED, next_state)


def test_claim_from_created_or_retrying():
    assert next_state(CREATED, "claim") == CLAIMED
    assert next_state(RETRYING, "claim") == CLAIMED


def test_succeed_from_claimed_or_executing():
    assert next_state(CLAIMED, "succeed") == SUCCEEDED
    assert next_state(EXECUTING, "succeed") == SUCCEEDED


def test_fail_retries_until_dead_letter():
    assert next_state(CLAIMED, "fail", attempts=0, max_attempts=3) == RETRYING
    assert next_state(CLAIMED, "fail", attempts=1, max_attempts=3) == RETRYING
    assert next_state(CLAIMED, "fail", attempts=2, max_attempts=3) == DEAD_LETTER


def test_illegal_transitions_are_noops():
    assert next_state(SUCCEEDED, "claim") == SUCCEEDED
    assert next_state(CREATED, "succeed") == CREATED
    assert next_state(DEAD_LETTER, "claim") == DEAD_LETTER
