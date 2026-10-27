#!/usr/bin/env python3
"""Bounded refresh and frozen-forecast verification. No timestamped backup copies.

python verification.py --dir <batch> --code 600039 --offline
python verification.py --dir <batch> --freeze --offline --code 600039
A baseline is written once, with its input hash. Re-running never replaces it.
"""
from __future__ import annotations
import argparse
import calendar
import hashlib
import json
import math
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from run_support import atomic_json, now, run_process

if __name__ == '__main__' and '--_verification-worker' not in sys.argv:
    guard = argparse.ArgumentParser(add_help=False)
    guard.add_argument('--total-timeout', type=float, default=240)
    options, _ = guard.parse_known_args()
    try:
        result = run_process([sys.executable, '-u', str(Path(__file__).resolve()), *sys.argv[1:], '--_verification-worker'],
                             timeout=options.total_timeout, heartbeat=10, label='复验总流程')
    except ValueError as exc:
        guard.error(str(exc))
    raise SystemExit(124 if result['status']=='TIMEOUT' else result.get('exit_code') or (0 if result['status']=='PASS' else 1))

import pandas as pd
from fetch_with_fallback import add_fetch_options, fetch_datasets


def finite(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError, OverflowError):
        return None


def col(frame, *names):
    if frame is None:
        return None
    return next((name for name in names if name in frame.columns), None)


def load_frame(data, filename, warnings):
    path = data / filename
    try:
        frame = pd.read_csv(path, dtype=str, encoding='utf-8-sig')
        return frame if not frame.empty else None
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        warnings.append(f'{filename} 不可用: {type(exc).__name__}')
        return None


def dated(frame, warnings, label):
    key = col(frame, 'REPORT_DATE', '报告期', '报告日期', 'END_DATE', 'end_date')
    if key is None:
        warnings.append(f'{label} 缺少报告日期')
        return None
    result = frame.copy()
    result['_date'] = pd.to_datetime(result[key], errors='coerce')
    if result['_date'].duplicated().any():
        warnings.append(f'{label} 有重复日期，保留末条并需核对披露版本')
    return result.dropna(subset=['_date']).sort_values('_date').drop_duplicates('_date', keep='last')


def at(frame, date, names):
    key = col(frame, *names)
    if frame is None or key is None:
        return None
    rows = frame.loc[frame['_date'].eq(date), key]
    return finite(rows.iloc[-1]) if len(rows) else None


def fingerprint_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _has_prediction_values(value):
    """Return whether a forecast/scenario tree contains a finite prediction."""
    if isinstance(value, dict):
        ignored = {'probability', 'weight', 'confidence', 'status', 'source', 'unit', 'currency', 'scope', 'basis',
                   'id', 'metric', 'period', 'date', 'period_end', 'entity', 'source_ref', 'published_at', 'observed_at'}
        for key, item in value.items():
            if str(key).lower() in ignored:
                continue
            if isinstance(item, (dict, list)) and _has_prediction_values(item):
                return True
            if not isinstance(item, (dict, list, bool)) and finite(item) is not None:
                return True
    elif isinstance(value, list):
        return any(_has_prediction_values(item) if isinstance(item, (dict, list))
                   else not isinstance(item, bool) and finite(item) is not None for item in value)
    return False


def freeze_baseline(project):
    project = Path(project)
    target = project / 'input' / '预测基线.json'
    if target.exists():
        return json.loads(target.read_text(encoding='utf-8-sig')), False
    source = next((p for p in (project/'input/研究模型.json', project/'input/估值模型.json', project/'reports/估值模型.json') if p.is_file()), None)
    if source is None:
        raise ValueError('没有可冻结的研究模型或估值模型输入')
    model = json.loads(source.read_text(encoding='utf-8-sig'))
    if not isinstance(model, dict):
        raise ValueError('冻结模型必须为JSON对象')
    # Writing an empty scaffold would create a misleading immutable baseline.
    if not (_has_prediction_values(model.get('forecast')) or _has_prediction_values(model.get('scenarios'))):
        raise ValueError('模型尚无预测，不能冻结空基线')
    payload = {'schema_version':1, 'frozen_at':now(), 'source':str(source.relative_to(project)),
               'source_sha256':fingerprint_file(source), 'model':model}
    # Serialize before exclusive creation so unsupported values cannot leave
    # an empty file that looks like an immutable frozen baseline.
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Exclusive creation ensures a concurrent invocation cannot replace an established baseline.
        with target.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(serialized)
            stream.flush()
    except FileExistsError:
        return json.loads(target.read_text(encoding='utf-8-sig')), False
    return payload, True


def _period_end(value):
    """Resolve an annual, quarter, or ISO forecast period to its period end."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        if re.fullmatch(r'\d{4}', text):
            return date(int(text), 12, 31)
        match = re.fullmatch(r'(\d{4})[- ]?[Qq]([1-4])', text)
        if match:
            year, quarter = map(int, match.groups())
            month = quarter * 3
            return date(year, month, calendar.monthrange(year, month)[1])
        return date.fromisoformat(text[:10])
    except (ValueError, TypeError, OverflowError):
        return None


def _parse_instant(value):
    """Parse ISO dates/timestamps as UTC instants; date-only values mean midnight UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _comparison_instant(actual):
    for key in ('published_at', 'observed_at', 'date', 'period_end'):
        value = actual.get(key)
        if isinstance(value, str):
            parsed = _parse_instant(value)
            if parsed is not None:
                return parsed
            parsed_date = _period_end(value)
            if parsed_date is not None:
                return datetime.combine(parsed_date, datetime.min.time(), timezone.utc)
    return None


def _frozen_instant(value):
    parsed = _parse_instant(value)
    if parsed is not None:
        return parsed
    parsed_date = _period_end(value)
    return datetime.combine(parsed_date, datetime.min.time(), timezone.utc) if parsed_date else None


def compare_predictions(forecasts, actuals, frozen_at=None):
    """Compare unique, identical records only when the target was forward at freeze.

    Actuals need a publication, observation, or explicit period-end date. Zero
    and negative forecasts retain signed/absolute errors without percentage
    errors.  Missing periods, duplicate actuals and absent baselines never score.
    """
    results = []
    keys = ('metric', 'period', 'unit', 'scope', 'basis')
    frozen_instant = _frozen_instant(frozen_at)
    for forecast in forecasts if isinstance(forecasts, list) else []:
        if not isinstance(forecast, dict):
            continue
        estimate = None if isinstance(forecast.get('value'), bool) else finite(forecast.get('value'))
        row = {'id':forecast.get('id'), 'metric':forecast.get('metric'), 'period':forecast.get('period'),
               'status':'NOT_COMPARABLE', 'reason':None, 'forecast':estimate, 'actual':None}
        if all(isinstance(forecast.get(k), str) and forecast[k].strip() for k in keys):
            actual_rows = actuals if isinstance(actuals, list) else []
            matches = [a for a in actual_rows if isinstance(a, dict) and all(a.get(k)==forecast[k] for k in keys)
                       and all((key not in forecast and key not in a) or a.get(key)==forecast.get(key) for key in ('entity', 'currency'))]
            if len(matches) != 1:
                row['reason'] = 'ACTUAL_MISSING_OR_DUPLICATE'
                results.append(row)
                continue
            actual = None if isinstance(matches[0].get('value'), bool) else finite(matches[0].get('value'))
            observed = _comparison_instant(matches[0]) if len(matches)==1 else None
            target_period_end = _period_end(forecast.get('period'))
            if frozen_instant is None:
                row['reason'] = 'NO_FROZEN_DATE'
            elif target_period_end is None or target_period_end <= frozen_instant.date():
                row['reason'] = 'TARGET_PERIOD_NOT_FORWARD'
            elif observed is None:
                row['reason'] = 'ACTUAL_DATE_MISSING'
            elif observed < frozen_instant:
                row['reason'] = 'OBSERVATION_BEFORE_FREEZE'
            elif actual is None or row['forecast'] is None:
                row['reason'] = 'VALUE_MISSING_OR_INVALID'
            else:
                error = finite(actual-row['forecast'])
                if error is None:
                    row['reason'] = 'VALUE_MISSING_OR_INVALID'
                else:
                    row.update(status='COMPARED', reason=None, actual=actual, error=error, absolute_error=abs(error),
                               relative_error=finite(error/row['forecast']) if row['forecast']>0 else None)
        else:
            row['reason'] = 'METADATA_MISSING'
        results.append(row)
    comparable = [r for r in results if r['status']=='COMPARED']
    return {'records':results, 'n':len(comparable), 'mae':sum(r['absolute_error']/len(comparable) for r in comparable) if comparable else None,
            'mean_signed_error':sum(r['error']/len(comparable) for r in comparable) if comparable else None,
            'interpretation':'同口径经营预测误差；不是投资胜率或收益回测'}


def verify(project, code, market, *, offline=False, freeze=False, fetch_options=None):
    project = Path(project).resolve()
    data = project/'data'
    warnings = []
    refresh = {'status':'OFFLINE', 'note':'使用存量数据，未刷新为最新披露'}
    if not offline:
        refresh = fetch_datasets(code, market, data, items={'sheets','indicators','daily','profile'}, **(fetch_options or {}))
        if refresh['status'] != 'PASS':
            warnings.append('本轮部分拉取失败；旧文件保留，不代表本轮更新成功')
    baseline_path = project/'input/预测基线.json'
    if freeze:
        frozen, created = freeze_baseline(project)
        print('[基线] ' + ('已冻结' if created else '沿用原冻结版本'), flush=True)
    elif baseline_path.is_file():
        frozen = json.loads(baseline_path.read_text(encoding='utf-8-sig'))
    else:
        legacy = next((p for p in (project/'input/估值模型.json', project/'reports/估值模型.json') if p.is_file()), None)
        frozen = {'model':json.loads(legacy.read_text(encoding='utf-8-sig')) if legacy else {}, 'frozen_at':None}
        warnings.append('无冻结预测基线；旧模型仅供参考，不能计入正式预测回测')
    model = frozen.get('model', {})
    income = dated(load_frame(data,'利润表_按报告期.csv',warnings),warnings,'利润表')
    balance = dated(load_frame(data,'资产负债表_按报告期.csv',warnings),warnings,'资产负债表')
    indicators = dated(load_frame(data,'主要财务指标_按报告期.csv',warnings),warnings,'财务指标')
    report_date = income['_date'].iloc[-1] if income is not None and not income.empty else None
    cum = ttm = shares = equity = bps = price = None
    price_date = None
    if report_date is not None:
        cum = at(income,report_date,('PARENT_NETPROFIT','归母净利润','n_income_attr_p'))
        if report_date.month == 12:
            ttm = cum
        else:
            annual = at(income,pd.Timestamp(report_date.year-1,12,31),('PARENT_NETPROFIT','归母净利润','n_income_attr_p'))
            prior = at(income,report_date-pd.DateOffset(years=1),('PARENT_NETPROFIT','归母净利润','n_income_attr_p'))
            if all(v is not None for v in (cum,annual,prior)):
                ttm = cum+annual-prior
        equity = at(balance,report_date,('TOTAL_PARENT_EQUITY','归母权益','total_hldr_eqy_exc_min_int'))
        bps = at(indicators,report_date,('BPS','每股净资产','bps'))
        shares = equity/bps if equity is not None and bps is not None and bps>0 else None
    profile = load_frame(data,'公司概况.csv',warnings)
    if profile is not None and len(profile.columns)>=2:
        for label, value in profile.iloc[:,:2].itertuples(index=False,name=None):
            if '总股本' in str(label):
                number = finite(value)
                if number is not None and number>0:
                    number *= 1e8 if '亿' in str(label) else 1e4 if '万' in str(label) else 1
                    if shares is not None and abs(number/shares-1)>.02:
                        warnings.append('概况股本与报表推算股本差异超过2%，须核对回购/股本日期')
                    shares = number
    prices = load_frame(data,'日线股价.csv',warnings)
    dc = col(prices,'date','日期','trade_date')
    pc = col(prices,'close','收盘','收盘价')
    if dc and pc:
        prices['_date'] = pd.to_datetime(prices[dc],errors='coerce')
        prices['_price'] = pd.to_numeric(prices[pc],errors='coerce')
        prices = prices.dropna(subset=['_date','_price']).sort_values('_date')
        if len(prices):
            price = finite(prices['_price'].iloc[-1])
            price_date = str(prices['_date'].iloc[-1].date())
    eps = ttm/shares if ttm is not None and shares is not None and shares>0 else None
    pe = price/eps if price is not None and eps is not None and eps>0 else None
    pb = price/bps if price is not None and bps is not None and bps>0 else None
    cap = price*shares/1e8 if price is not None and shares is not None else None
    baseline = model.get('scenarios',{}).get('基准',{})
    if report_date is not None:
        year = str(report_date.year)
        fy = finite(baseline.get(year)) if isinstance(baseline,dict) else None
        if fy is not None and fy>0 and cum is not None:
            print(f'{year}E 完成进度：{cum/1e8:.2f} 亿元 / {fy} 亿元 = {cum/1e8/fy:.0%}（累计/全年，非预测误差）',flush=True)
    actuals = []
    if income is not None:
        for _, row in income.iterrows():
            if row['_date'].month==12:
                value=at(income,row['_date'],('PARENT_NETPROFIT','归母净利润','n_income_attr_p'))
                actuals.append({'metric':'net_profit_parent','period':str(row['_date'].year),'unit':'CNY','scope':'parent','basis':'reported','value':value,
                                'period_end':str(row['_date'].date()), 'observed_at':now()})
    explicit_actuals = model.get('verification_actuals', [])
    if isinstance(explicit_actuals,list):
        actuals.extend(explicit_actuals)
    comparison = compare_predictions(model.get('forecast',{}).get('estimates',[]) if isinstance(model.get('forecast'),dict) else [],
                                     actuals, frozen.get('frozen_at'))
    if not frozen.get('frozen_at'):
        comparison = {'records':[], 'n':0, 'mae':None, 'mean_signed_error':None, 'status':'NO_FROZEN_BASELINE'}
    snap = {'schema_version':2,'generated_at':now(),'symbol':f'{market}.{code}',
            'status':'INCOMPLETE' if report_date is None or cum is None or price is None else 'OK',
            'latest_report_date':str(report_date.date()) if report_date is not None else None,
            'latest_cumulative_ni_yi':round(cum/1e8,2) if cum is not None else None,
            'ttm_ni_yi':round(ttm/1e8,2) if ttm is not None else None,
            'shares_yi':round(shares/1e8,2) if shares is not None else None,
            'price':price,'price_date':price_date,'pe_ttm':round(pe,1) if pe is not None else None,
            'pb':round(pb,2) if pb is not None else None,'market_cap_yi':round(cap,1) if cap is not None else None,
            'baseline':model,'baseline_frozen_at':frozen.get('frozen_at'), 'comparison':comparison,
            'refresh_status':refresh['status'],'warnings':warnings,
            'source_hashes':{p.name:fingerprint_file(p) for p in data.glob('*.csv')}}
    atomic_json(data/'验证快照.json',snap)
    print(f"[复验] {snap['status']}；数据刷新={refresh['status']}；同口径预测比较n={comparison['n']}",flush=True)
    return snap


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dir',default='.')
    parser.add_argument('--code')
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--freeze',action='store_true')
    parser.add_argument('--total-timeout',type=float,default=240)
    parser.add_argument('--_verification-worker',action='store_true',help=argparse.SUPPRESS)
    add_fetch_options(parser)
    args=parser.parse_args(argv)
    project=Path(args.dir).resolve()
    match=next((re.search(r'(SH|SZ|BJ)\.(\d{6})',p.name) for p in (project,*project.parents) if re.search(r'(SH|SZ|BJ)\.(\d{6})',p.name)),None)
    code=args.code or (match.group(2) if match else None)
    if not code or not re.fullmatch(r'\d{6}',code):
        parser.error('当前自动复验适配A股六位代码；请用 --code 指定，其他市场需专用数据适配')
    market=match.group(1) if match and match.group(2)==code else 'SH' if code.startswith(('6','9')) else 'BJ' if code.startswith(('4','8','92')) else 'SZ'
    try:
        result=verify(project,code,market,offline=args.offline,freeze=args.freeze,
                      fetch_options=dict(timeout=args.timeout,retries=args.retries,failure_ttl=args.failure_ttl,
                                         force=args.force_refresh,total_budget=args.fetch_budget,success_ttl=args.success_ttl))
        return 0 if result['status']=='OK' else 2
    except (OSError,ValueError,KeyError,TypeError) as exc:
        atomic_json(project/'data/验证快照.json',{'status':'FAIL','generated_at':now(),'error':str(exc)})
        print(f'[复验] FAIL: {exc}',flush=True)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
