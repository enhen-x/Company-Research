"""Deterministic offline regression tests for frozen forward-prediction scores."""
import copy
import hashlib
import json

import pytest

import verification as subject


FROZEN_AT = '2026-10-28T12:00:00+00:00'


def estimate(**changes):
    result = {'id': 'E1', 'metric': 'net_profit_parent', 'period': '2026',
              'unit': 'CNY', 'scope': 'parent', 'basis': 'reported', 'value': 100}
    result.update(changes)
    return result


def actual(**changes):
    result = estimate(value=110)
    result['published_at'] = '2027-03-28T12:00:00+00:00'
    result.update(changes)
    return result


def write_model(project, payload):
    folder = project / 'input'
    folder.mkdir(exist_ok=True)
    source = folder / '研究模型.json'
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return source


def comparison(forecast=None, observed=None, frozen_at=FROZEN_AT):
    return subject.compare_predictions([forecast or estimate()], [observed or actual()], frozen_at)


def test_freeze_is_write_once_and_keeps_original_input_hash(tmp_path, monkeypatch):
    source = write_model(tmp_path, {'forecast': {'estimates': [estimate()]}})
    first_source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(subject, 'now', lambda: FROZEN_AT)
    frozen, created = subject.freeze_baseline(tmp_path)
    target = tmp_path / 'input/预测基线.json'
    before = target.read_bytes()
    before_mtime = target.stat().st_mtime_ns
    write_model(tmp_path, {'forecast': {'estimates': [estimate(value=999)]}})
    monkeypatch.setattr(subject, 'now', lambda: '2027-01-01T00:00:00+00:00')
    again, created_again = subject.freeze_baseline(tmp_path)
    assert created is True
    assert created_again is False
    assert frozen == again
    assert frozen['source_sha256'] == first_source_hash
    assert frozen['model']['forecast']['estimates'][0]['value'] == 100
    assert target.read_bytes() == before
    assert target.stat().st_mtime_ns == before_mtime
    assert sorted(p.name for p in target.parent.iterdir()) == ['研究模型.json', '预测基线.json']


@pytest.mark.parametrize('bad_value', [float('nan'), float('inf'), -float('inf')])
def test_serialization_failure_leaves_no_empty_baseline(tmp_path, bad_value):
    # A valid finite estimate ensures failure is serialization, not scaffold validation.
    write_model(tmp_path, {'forecast': {'estimates': [estimate()]}, 'bad_value': bad_value})
    with pytest.raises(ValueError):
        subject.freeze_baseline(tmp_path)
    assert not (tmp_path / 'input/预测基线.json').exists()
    assert len(list((tmp_path / 'input').iterdir())) == 1


@pytest.mark.parametrize('payload', [
    {}, {'forecast': {}}, {'forecast': {'estimates': []}},
    {'forecast': {'estimates': [{'period': '2026', 'value': None}]}},
    {'forecast': {'estimates': [{'period': '2026', 'value': True}]}},
    {'scenarios': {'base': {'probability': 1, 'cashflows': []}}},
])
def test_empty_or_metadata_only_scaffolds_cannot_be_frozen(tmp_path, payload):
    write_model(tmp_path, payload)
    with pytest.raises(ValueError, match='空基线'):
        subject.freeze_baseline(tmp_path)
    assert not (tmp_path / 'input/预测基线.json').exists()


@pytest.mark.parametrize('payload', [
    {'forecast': {'estimates': [estimate(value=0)]}},
    {'scenarios': {'基准': {'2026': -10}}},
    {'scenarios': {'base': {'cashflows': [0, -10, 20]}}},
])
def test_real_zero_or_negative_predictions_are_not_empty(tmp_path, payload):
    write_model(tmp_path, payload)
    frozen, created = subject.freeze_baseline(tmp_path)
    assert created is True
    assert frozen['model'] == payload


def test_comparison_has_known_absolute_and_relative_error():
    result = comparison()
    row = result['records'][0]
    assert result['n'] == 1
    assert row['status'] == 'COMPARED'
    assert row['error'] == row['absolute_error'] == 10
    assert row['relative_error'] == pytest.approx(.1)
    assert result['mae'] == result['mean_signed_error'] == 10


@pytest.mark.parametrize('forecast_value,actual_value,error', [(0, 10, 10), (-10, -15, -5), (-10, 0, 10)])
def test_zero_negative_forecasts_keep_errors_without_percentage(forecast_value, actual_value, error):
    result = comparison(estimate(value=forecast_value), actual(value=actual_value))
    row = result['records'][0]
    assert result['n'] == 1
    assert row['error'] == error
    assert row['absolute_error'] == abs(error)
    assert row['relative_error'] is None


@pytest.mark.parametrize('field,changed', [
    ('metric', 'revenue'), ('period', '2027'), ('unit', 'million CNY'),
    ('scope', 'consolidated'), ('basis', 'adjusted'), ('currency', 'USD'), ('entity', 'OTHER'),
])
def test_metadata_mismatch_never_scores(field, changed):
    result = comparison(observed=actual(**{field: changed}))
    assert result['n'] == 0
    assert result['records'][0]['reason'] == 'ACTUAL_MISSING_OR_DUPLICATE'


@pytest.mark.parametrize('value', [None, '', ' ', 2026])
def test_missing_or_nonstring_forecast_period_never_scores(value):
    result = comparison(estimate(period=value))
    assert result['n'] == 0
    assert result['records'][0]['reason'] == 'METADATA_MISSING'


def test_missing_actual_period_never_scores():
    observed = actual()
    del observed['period']
    result = comparison(observed=observed)
    assert result['n'] == 0
    assert result['records'][0]['reason'] == 'ACTUAL_MISSING_OR_DUPLICATE'


@pytest.mark.parametrize('frozen_at', [None, '', 'not-a-date'])
def test_absent_or_invalid_freeze_date_never_scores(frozen_at):
    result = comparison(frozen_at=frozen_at)
    assert result['n'] == 0
    assert result['records'][0]['reason'] == 'NO_FROZEN_DATE'


@pytest.mark.parametrize('period', ['2025', '2026-Q3', '2026-10-28', 'unknown'])
def test_historical_or_unresolved_target_period_never_scores(period):
    result = comparison(estimate(period=period), actual(period=period))
    assert result['n'] == 0
    assert result['records'][0]['reason'] == 'TARGET_PERIOD_NOT_FORWARD'


@pytest.mark.parametrize('observed', ['2026-10-27T23:59:59+00:00', '2026-10-28T11:59:59+00:00',
                                      '2026-10-28T19:59:59+08:00', '2026-10-28'])
def test_observation_before_precise_freeze_instant_never_scores(observed):
    result = comparison(observed=actual(published_at=observed))
    assert result['n'] == 0
    assert result['records'][0]['reason'] == 'OBSERVATION_BEFORE_FREEZE'


def test_timezone_equivalent_observation_is_not_earlier():
    result = comparison(observed=actual(published_at='2026-10-28T20:00:00+08:00'))
    assert result['n'] == 1


def test_missing_actual_timestamp_does_not_infer_observation_from_period():
    observed = actual()
    del observed['published_at']
    result = comparison(observed=observed)
    assert result['n'] == 0
    assert result['records'][0]['reason'] == 'ACTUAL_DATE_MISSING'


def test_quarter_period_uses_real_calendar_end():
    result = comparison(estimate(period='2026-Q4'), actual(period='2026-Q4'))
    assert result['n'] == 1


@pytest.mark.parametrize('actuals', [None, {}, [actual(), actual()]])
def test_missing_malformed_or_duplicate_actuals_never_score(actuals):
    result = subject.compare_predictions([estimate()], actuals, FROZEN_AT)
    assert result['n'] == 0
    assert result['records'][0]['reason'] == 'ACTUAL_MISSING_OR_DUPLICATE'


@pytest.mark.parametrize('value', [None, True, float('nan'), float('inf')])
def test_invalid_values_never_score(value):
    result = comparison(estimate(value=value))
    assert result['n'] == 0
    assert result['records'][0]['reason'] == 'VALUE_MISSING_OR_INVALID'


def test_overflow_error_is_unscored_and_serializable():
    result = comparison(estimate(value=-1e308), actual(value=1e308))
    assert result['n'] == 0
    assert result['records'][0]['reason'] == 'VALUE_MISSING_OR_INVALID'
    json.dumps(result, allow_nan=False)


def test_comparison_does_not_mutate_inputs():
    forecasts, actuals = [estimate()], [actual()]
    before = copy.deepcopy((forecasts, actuals))
    subject.compare_predictions(forecasts, actuals, FROZEN_AT)
    assert (forecasts, actuals) == before
