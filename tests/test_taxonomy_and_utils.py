import pytest

from jobagent.config import Weights
from jobagent.logging_setup import redact
from jobagent.utils.files import sanitize_filename_part
from jobagent.utils.retry import PermanentError, RateLimiter, TransientError, retry_call


def test_synonyms_map_to_one_canonical_skill(taxonomy):
    found = taxonomy.find("Postgres, PostgreSQL and psql; T-SQL and SQL")
    assert set(found) == {"PostgreSQL", "SQL"}  # no double counting of synonyms


def test_longest_alias_wins_over_substring(taxonomy):
    assert set(taxonomy.find("Experience with SQL Server")) == {"Microsoft SQL Server"}


@pytest.mark.parametrize("text", ["Go to the office daily", "Rest of the team", "R&D department", "Node.js not needed"])
def test_common_words_are_not_skills(taxonomy, text):
    assert taxonomy.find(text) == {}


def test_implications_and_transfer(taxonomy):
    assert {"AWS", "SQL"} <= taxonomy.implied_closure({"AWS Lambda", "PostgreSQL"})
    credit, via = taxonomy.transfer_credit("Snowflake", {"Amazon Redshift"})
    assert credit == pytest.approx(0.7) and via == "Amazon Redshift"
    assert taxonomy.transfer_credit("Apache Airflow", {"AWS Step Functions"})[0] == pytest.approx(0.35)
    assert taxonomy.transfer_credit("Apache Kafka", {"Power BI"}) == (0.0, None)


def test_weights_must_sum_to_100():
    with pytest.raises(ValueError):
        Weights(skills=50)


def test_redaction_hides_secrets_and_contact_details():
    out = redact("key=sk-ant-abcdefghijklmnopq email me@x.com phone 0300-1234567 cookie: li_at=abc")
    assert "sk-ant" not in out and "me@x.com" not in out and "1234567" not in out and "abc" not in out


def test_retry_retries_transient_but_not_permanent():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("timeout")
        return "ok"

    assert retry_call(flaky, max_attempts=3, sleep=lambda s: None) == "ok"
    calls["n"] = 0

    def perm():
        calls["n"] += 1
        raise PermanentError("404")

    with pytest.raises(PermanentError):
        retry_call(perm, max_attempts=5, sleep=lambda s: None)
    assert calls["n"] == 1


def test_retry_gives_up_after_max_attempts():
    with pytest.raises(TransientError):
        retry_call(lambda: (_ for _ in ()).throw(TransientError("x")), max_attempts=2, sleep=lambda s: None)


def test_rate_limiter_waits_between_calls():
    t = {"now": 0.0}
    slept = []
    rl = RateLimiter(5, clock=lambda: t["now"], sleep=lambda s: (slept.append(s), t.__setitem__("now", t["now"] + s)))
    rl.wait("h")
    t["now"] += 1
    rl.wait("h")
    assert slept == [4]


def test_filename_sanitisation():
    assert sanitize_filename_part("Acme (Pvt) Ltd / Lahore: Data Eng.") == "Acme_Pvt_Ltd_Lahore_Data_Eng"
    assert sanitize_filename_part("") == "Unknown"
