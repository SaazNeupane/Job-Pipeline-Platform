from datetime import datetime, timedelta, timezone

from pipeline.config import Lane
from pipeline.filter import filter_postings, posting_fingerprint
from pipeline.search import Posting


def _posting(**overrides) -> Posting:
    defaults = dict(
        source="greenhouse",
        company="Acme Co",
        job_id="123",
        title="Software Engineer",
        url="https://example.com/job/123",
        location="Toronto, ON",
        description_text="Build things with Python.",
        posted_at=datetime.now(timezone.utc).isoformat(),
    )
    defaults.update(overrides)
    return Posting(**defaults)


def _lane(**overrides) -> Lane:
    defaults = dict(
        name="it_tech",
        resume="it_tech",
        keywords=["python", "software"],
        sources=["greenhouse"],
    )
    defaults.update(overrides)
    return Lane(**defaults)


def test_matches_on_keyword_in_title():
    postings = [_posting(title="Python Developer")]
    results = filter_postings(postings, _lane(), existing_keys=set(), target_countries=["ca"])
    assert len(results) == 1
    assert "python" in results[0][1]


def test_excludes_posting_with_no_keyword_match():
    postings = [_posting(title="Warehouse Associate", description_text="Lift boxes.")]
    results = filter_postings(postings, _lane(), existing_keys=set(), target_countries=["ca"])
    assert results == []


def test_dedupe_by_existing_key_excludes_already_seen_posting():
    p = _posting()
    results = filter_postings(
        [p], _lane(), existing_keys={p.dedupe_key()}, target_countries=["ca"]
    )
    assert results == []


def test_dedupe_by_fingerprint_catches_reindexed_posting():
    # Adzuna re-lists the same job under a brand new ad id -- posting_key alone (job_id-based)
    # lets it back in looking "new." The fingerprint (source+company+title+location) catches
    # that even with a different job_id.
    p = _posting(job_id="new-id-999")
    fp = posting_fingerprint(p.source, p.company, p.title, p.location)
    results = filter_postings(
        [p], _lane(), existing_keys=set(), existing_fingerprints={fp}, target_countries=["ca"]
    )
    assert results == []


def test_fingerprint_dedupe_is_case_and_whitespace_insensitive():
    p = _posting(company="Acme   Co", title="Software  Engineer")
    fp = posting_fingerprint("greenhouse", "acme co", "software engineer", "toronto, on")
    results = filter_postings(
        [p], _lane(), existing_keys=set(), existing_fingerprints={fp}, target_countries=["ca"]
    )
    assert results == []


def test_stale_posting_excluded_past_recency_window():
    old = _posting(posted_at=(datetime.now(timezone.utc) - timedelta(days=30)).isoformat())
    results = filter_postings([old], _lane(), existing_keys=set(), target_countries=["ca"])
    assert results == []


def test_missing_posted_at_fails_open_as_recent():
    p = _posting(posted_at="")
    results = filter_postings([p], _lane(), existing_keys=set(), target_countries=["ca"])
    assert len(results) == 1


def test_seniority_cap_excludes_senior_title():
    p = _posting(title="Senior Python Engineer")
    results = filter_postings(
        [p], _lane(seniority_max="entry"), existing_keys=set(), target_countries=["ca"]
    )
    assert results == []


def test_seniority_cap_allows_unlabeled_title():
    p = _posting(title="Python Engineer")
    results = filter_postings(
        [p], _lane(seniority_max="entry"), existing_keys=set(), target_countries=["ca"]
    )
    assert len(results) == 1


def test_required_keywords_must_include_at_least_one():
    p = _posting(title="Software role", description_text="python and django")
    lane = _lane(keywords=["python", "django"], required_keywords=["golang"])
    results = filter_postings([p], lane, existing_keys=set(), target_countries=["ca"])
    assert results == []


def test_out_of_target_country_excluded_for_non_adzuna_source():
    p = _posting(source="greenhouse", location="Berlin, Germany")
    results = filter_postings([p], _lane(), existing_keys=set(), target_countries=["ca"])
    assert results == []


def test_adzuna_source_skips_location_check():
    # Adzuna's API is already scoped by country server-side -- re-checking the location
    # string client-side risks a false exclusion on a format that doesn't match the
    # curated alias tables.
    p = _posting(source="adzuna", location="Some Unrecognized Format")
    results = filter_postings([p], _lane(sources=["adzuna"]), existing_keys=set(), target_countries=["ca"])
    assert len(results) == 1


def test_target_regions_excludes_other_provinces():
    p = _posting(location="Vancouver, BC")
    results = filter_postings(
        [p], _lane(), existing_keys=set(), target_countries=["ca"], target_regions=["on"],
    )
    assert results == []


def test_target_regions_matches_named_province():
    p = _posting(location="Toronto, ON")
    results = filter_postings(
        [p], _lane(), existing_keys=set(), target_countries=["ca"], target_regions=["on"],
    )
    assert len(results) == 1


def test_target_regions_applies_even_to_adzuna():
    # Unlike target_countries, target_regions has no "already correct by construction"
    # exemption for Adzuna -- Adzuna only scopes requests by country, never by province/state.
    p = _posting(source="adzuna", location="Vancouver, BC")
    results = filter_postings(
        [p], _lane(sources=["adzuna"]), existing_keys=set(), target_countries=["ca"], target_regions=["on"],
    )
    assert results == []
