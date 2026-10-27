#!/usr/bin/env python3
"""Rebuild nhl.json for the Five Hole NHL pages.

Sources (all free and public, no key):
  * NHL web API (api-web.nhle.com): standings, schedule, team schedules,
    club stats (goalies), current rosters and box scores.
  * NHL stats API (api.nhle.com/stats/rest): power play, penalty kill,
    shots and faceoffs.
  * ESPN's public NHL injuries feed (site.api.espn.com).

Run from the repository root:
    python scripts/build_nhl.py
"""
import os, sys, json, time, base64, datetime, unicodedata, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'nhl.json')
WEB = os.environ.get('NHL_WEB', 'https://api-web.nhle.com/v1')
STATS = os.environ.get('NHL_STATS', 'https://api.nhle.com/stats/rest/en')
ESPN = os.environ.get('NHL_ESPN', 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries')
ESPN_SB = os.environ.get('NHL_ESPN_SB', 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard')
MSF = os.environ.get('MSF_BASE', 'https://api.mysportsfeeds.com/v2.1/pull/nhl')
MSF_KEY = os.environ.get('MSF_API_KEY', '').strip()
LAST_N = 7
WARN = []


def _report_crash(exc_type, exc, tb):
    import traceback
    msg = ''.join(traceback.format_exception(exc_type, exc, tb))
    sys.__excepthook__(exc_type, exc, tb)
    try:
        old = json.load(open(OUT)) if os.path.exists(OUT) else {}
        old['buildError'] = msg[-3000:]
        old['buildErrorAt'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
        with open(OUT, 'w') as f:
            json.dump(old, f, separators=(',', ':'))
    except Exception:  # noqa: BLE001
        pass


sys.excepthook = _report_crash


def get(url, tries=3, auth=None):
    for i in range(tries):
        try:
            hdr = {'User-Agent': 'fivehole-builder', 'Accept': 'application/json'}
            if auth:
                hdr['Authorization'] = 'Basic ' + base64.b64encode(f'{auth}:MYSPORTSFEEDS'.encode()).decode()
            req = urllib.request.Request(url, headers=hdr)
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                WARN.append(f'{url}: {e}')
                return None
            time.sleep(1.5 * (i + 1))


def txt(v):
    """NHL API strings are often {"default": "..."}."""
    if isinstance(v, dict):
        return v.get('default') or next(iter(v.values()), '')
    return v or ''


def norm(s):
    s = unicodedata.normalize('NFKD', txt(s)).encode('ascii', 'ignore').decode().lower()
    return ''.join(ch for ch in s if ch.isalnum())


def dget(v, k, d=None):
    """Like v.get(k) but tolerant of v not being a dict."""
    return v.get(k, d) if isinstance(v, dict) else d


def num(v, d=0):
    try:
        return float(v) if v is not None else d
    except (TypeError, ValueError):
        return d


# ---------------------------------------------------------------- standings
st = get(f'{WEB}/standings/now') or {}
rows = st.get('standings') or []
if not rows:
    raise SystemExit('No standings returned; leaving nhl.json unchanged. ' + '; '.join(WARN))
season = str(rows[0].get('seasonId') or '')
teams = {}
for r in rows:
    ab = txt(r.get('teamAbbrev'))
    gp = int(num(r.get('gamesPlayed')))
    hg = int(num(r.get('homeGamesPlayed'), num(r.get('homeWins')) + num(r.get('homeLosses')) + num(r.get('homeOtLosses'))))
    rg = int(num(r.get('roadGamesPlayed'), num(r.get('roadWins')) + num(r.get('roadLosses')) + num(r.get('roadOtLosses'))))
    teams[ab] = {
        'name': txt(r.get('teamName')), 'short': txt(r.get('teamCommonName')), 'place': txt(r.get('placeName')),
        'logo': r.get('teamLogo') or '', 'conf': r.get('conferenceName') or '', 'div': r.get('divisionName') or '',
        'gp': gp, 'w': int(num(r.get('wins'))), 'l': int(num(r.get('losses'))), 'otl': int(num(r.get('otLosses'))),
        'pts': int(num(r.get('points'))), 'ptsPct': num(r.get('pointPctg')),
        'rw': int(num(r.get('regulationWins'))), 'rotw': int(num(r.get('regulationPlusOtWins'))),
        'gf': int(num(r.get('goalFor'))), 'ga': int(num(r.get('goalAgainst'))),
        'home': {'gp': hg, 'w': int(num(r.get('homeWins'))), 'l': int(num(r.get('homeLosses'))), 'otl': int(num(r.get('homeOtLosses'))),
                 'gf': r.get('homeGoalsFor'), 'ga': r.get('homeGoalsAgainst')},
        'road': {'gp': rg, 'w': int(num(r.get('roadWins'))), 'l': int(num(r.get('roadLosses'))), 'otl': int(num(r.get('roadOtLosses'))),
                 'gf': r.get('roadGoalsFor'), 'ga': r.get('roadGoalsAgainst')},
        'so': {'w': int(num(r.get('shootoutWins'))), 'l': int(num(r.get('shootoutLosses')))},
        'l10': {'w': int(num(r.get('l10Wins'))), 'l': int(num(r.get('l10Losses'))), 'otl': int(num(r.get('l10OtLosses')))},
        'streak': f"{r.get('streakCode') or ''}{r.get('streakCount') or ''}",
        'divRank': int(num(r.get('divisionSequence'))), 'leagueRank': int(num(r.get('leagueSequence'))),
        'goalies': [], 'last7': [], 'injuries': [], 'stats': {},
    }
by_name = {norm(t['name']): ab for ab, t in teams.items()}

# ----------------------------------------------------- team summary (PP/PK...)
if season:
    q = f'{STATS}/team/summary?cayenneExp=seasonId={season}%20and%20gameTypeId=2'
    for r in (get(q) or {}).get('data', []):
        ab = by_name.get(norm(r.get('teamFullName')))
        if ab:
            teams[ab]['stats'] = {k: r.get(k) for k in ('powerPlayPct', 'penaltyKillPct', 'shotsForPerGame',
                                                         'shotsAgainstPerGame', 'faceoffWinPct')}

# ------------------------------------------------- per-team pulls (parallel)
def team_pull(ab):
    return ab, get(f'{WEB}/club-stats/{ab}/now'), get(f'{WEB}/club-schedule-season/{ab}/now'), get(f'{WEB}/roster/{ab}/current')

with ThreadPoolExecutor(max_workers=6) as ex:
    pulled = list(ex.map(team_pull, list(teams)))

finals = {}       # game id -> game dict from team schedules
sched_by_team = {}
for ab, cs, sc, ro in pulled:
    t = teams[ab]
    roster_ids = {g.get('id') for g in (ro or {}).get('goalies', [])} if ro else set()
    roster_names = {g.get('id'): f"{txt(g.get('firstName'))} {txt(g.get('lastName'))}".strip() for g in (ro or {}).get('goalies', [])} if ro else {}
    seen = set()
    for g in (cs or {}).get('goalies', []) or []:
        pid = g.get('playerId')
        if roster_ids and pid not in roster_ids:
            continue  # traded, waived or sent down
        seen.add(pid)
        t['goalies'].append({
            'id': pid, 'name': f"{txt(g.get('firstName'))} {txt(g.get('lastName'))}".strip(),
            'gp': int(num(g.get('gamesPlayed'))), 'gs': int(num(g.get('gamesStarted'))),
            'w': int(num(g.get('wins'))), 'l': int(num(g.get('losses'))), 'otl': int(num(g.get('overtimeLosses'))),
            'gaa': num(g.get('goalsAgainstAverage')), 'svp': num(g.get('savePercentage')),
            'so': int(num(g.get('shutouts'))), 'sa': int(num(g.get('shotsAgainst'))), 'sv': int(num(g.get('saves'))),
        })
    for pid, nm in roster_names.items():
        if pid not in seen:
            t['goalies'].append({'id': pid, 'name': nm, 'gp': 0, 'gs': 0, 'w': 0, 'l': 0, 'otl': 0,
                                 'gaa': 0, 'svp': 0, 'so': 0, 'sa': 0, 'sv': 0})
    games = [g for g in (sc or {}).get('games', []) if g.get('gameType') == 2]
    sched_by_team[ab] = games
    for g in games:
        if g.get('gameState') in ('OFF', 'FINAL'):
            finals[g['id']] = g

# last N finals per team, then box scores for starting goalies
need = set()
for ab, games in sched_by_team.items():
    done = [g for g in games if g.get('gameState') in ('OFF', 'FINAL')]
    done.sort(key=lambda g: g.get('startTimeUTC') or g.get('gameDate') or '')
    sched_by_team[ab] = (done[-LAST_N:], [g for g in games if g.get('gameState') not in ('OFF', 'FINAL')])
    need.update(g['id'] for g in done[-LAST_N:])

with ThreadPoolExecutor(max_workers=6) as ex:
    boxes = dict(zip(need, ex.map(lambda gid: get(f'{WEB}/gamecenter/{gid}/boxscore'), list(need))))


def starters(box, require_flag=False):
    out = {}
    pbs = (box or {}).get('playerByGameStats') or {}
    for side in ('homeTeam', 'awayTeam'):
        gl = (pbs.get(side) or {}).get('goalies') or []
        st_ = [g for g in gl if g.get('starter')]
        if not st_ and not require_flag:
            st_ = sorted(gl, key=lambda g: -num(g.get('shotsAgainst')))[:1]
        if st_:
            g = st_[0]
            out[side] = {'id': g.get('playerId'), 'name': txt(g.get('name')), 'sv': int(num(g.get('saves'))),
                         'sa': int(num(g.get('shotsAgainst'))), 'ga': int(num(g.get('goalsAgainst'))),
                         'dec': g.get('decision') or '', 'pulled': len(gl) > 1}
    return out


for ab, (done, _) in sched_by_team.items():
    log = []
    for g in done:
        home = txt(g['homeTeam'].get('abbrev')) == ab
        me, op = (g['homeTeam'], g['awayTeam']) if home else (g['awayTeam'], g['homeTeam'])
        gf, ga = int(num(me.get('score'))), int(num(op.get('score')))
        lpt = ((g.get('gameOutcome') or {}).get('lastPeriodType') or 'REG').upper()
        res = 'W' if gf > ga else ('OTL' if lpt in ('OT', 'SO') else 'L')
        s = starters(boxes.get(g['id'])).get('homeTeam' if home else 'awayTeam')
        log.append({'id': g['id'], 'date': g.get('gameDate') or (g.get('startTimeUTC') or '')[:10],
                    'opp': txt(op.get('abbrev')), 'home': home, 'gf': gf, 'ga': ga, 'res': res,
                    'ot': lpt if lpt in ('OT', 'SO') else '', 'goalie': s})
    teams[ab]['last7'] = list(reversed(log))

# ------------------------------------------------------ goalie game logs
GLOG_N = 10


def toi_min(v):
    try:
        m, sec = str(v).split(':')
        return int(m) + int(sec) / 60
    except (ValueError, AttributeError):
        return 0.0


def glog(pid):
    url = f'{WEB}/player/{pid}/game-log/{season}/2' if season else f'{WEB}/player/{pid}/game-log/now'
    rows_ = (get(url) or {}).get('gameLog') or []
    out = []
    for r in rows_[:GLOG_N]:
        sa, ga = int(num(r.get('shotsAgainst'))), int(num(r.get('goalsAgainst')))
        out.append({'date': r.get('gameDate') or '', 'opp': txt(r.get('opponentAbbrev')),
                    'home': (r.get('homeRoadFlag') or '') == 'H', 'gs': int(num(r.get('gamesStarted'))),
                    'dec': r.get('decision') or '', 'sa': sa, 'ga': ga, 'sv': sa - ga,
                    'svp': num(r.get('savePctg'), (sa - ga) / sa if sa else 0), 'toi': r.get('toi') or '',
                    'min': round(toi_min(r.get('toi')), 2), 'so': int(num(r.get('shutouts'))), 'id': r.get('gameId')})
    return pid, out


gids = [g['id'] for t in teams.values() for g in t['goalies'] if g.get('id')]
with ThreadPoolExecutor(max_workers=6) as ex:
    logs = dict(ex.map(glog, gids))
for t in teams.values():
    for g in t['goalies']:
        g['log'] = logs.get(g['id'], [])

# -------------------------------------------------------------- injuries
ESPN_STATUS = {'injured reserve': 'IR', 'out': 'Out', 'day-to-day': 'Day-to-day', 'suspension': 'Suspended',
               'long term injured reserve': 'LTIR'}
inj = get(ESPN) or {}
for grp in inj.get('injuries', []) or []:
    ab = by_name.get(norm(grp.get('displayName')))
    items = grp.get('injuries') or []
    for it in items:
        a = it.get('athlete') or {}
        if not ab:
            tm = a.get('team') or {}
            ab = by_name.get(norm(tm.get('displayName')))
        if not ab:
            continue
        stx = (it.get('status') or (it.get('type') or {}).get('description') or '').strip()
        det = it.get('details') or {}
        teams[ab]['injuries'].append({
            'name': a.get('displayName') or '', 'pos': ((a.get('position') or {}).get('abbreviation') or ''),
            'status': ESPN_STATUS.get(stx.lower(), stx), 'detail': det.get('type') or '',
            'side': det.get('side') or '', 'ret': (det.get('returnDate') or '')[:10],
            'note': it.get('shortComment') or '', 'date': (it.get('date') or '')[:10],
        })

# ------------------------------------------------- schedule + goalie picks
sch = get(f'{WEB}/schedule/now') or {}
games = []
for day in sch.get('gameWeek', []) or []:
    for g in day.get('games', []) or []:
        if g.get('gameType') not in (None, 2):
            continue
        games.append({'id': g.get('id'), 'date': day.get('date') or g.get('gameDate'),
                      'start': g.get('startTimeUTC') or '', 'state': g.get('gameState') or 'FUT',
                      'away': txt(g['awayTeam'].get('abbrev')), 'home': txt(g['homeTeam'].get('abbrev')),
                      'awayScore': g['awayTeam'].get('score'), 'homeScore': g['homeTeam'].get('score'),
                      'lastPeriod': ((g.get('gameOutcome') or {}).get('lastPeriodType') or '')})


# ------------------------------------- MySportsFeeds expected/actual goalies
# Optional. Set the MSF_API_KEY repository secret to enable it.
MSF_ALIAS = {'WPJ': 'WPG', 'ARI': 'UTA', 'UTAH': 'UTA', 'UTH': 'UTA', 'MON': 'MTL', 'LA': 'LAK', 'TB': 'TBL', 'NJ': 'NJD',
             'SJ': 'SJS', 'CLS': 'CBJ', 'CLB': 'CBJ', 'WAS': 'WSH', 'NAS': 'NSH', 'CAL': 'CGY', 'VEG': 'VGK', 'LV': 'VGK',
             'STL': 'STL', 'NYI': 'NYI', 'NYR': 'NYR'}
msf_pick = {}   # (nhl game id, team abbrev) -> {'name','status'}
MSF_STATUS = 'off'


def msf_abbr(a):
    a = (a or '').upper()
    return MSF_ALIAS.get(a, a)


def msf_goalie(positions):
    pos = [p for p in (positions or []) if p.get('player')]
    def is_start(p):
        n = (p.get('position') or '').lower()
        return n in ('goalie', 'g', 'starting goalie', 'goalie1') or ('goalie' in n and 'backup' not in n and n[-1:] not in '2')
    st_ = [p for p in pos if is_start(p)]
    if not st_:
        return None
    pl = st_[0]['player']
    return f"{pl.get('firstName', '')} {pl.get('lastName', '')}".strip()


MSF_OK = False
if MSF_KEY:
    MSF_STATUS = 'on'
    now = datetime.datetime.now(datetime.timezone.utc)
    soon = [g for g in games if g['state'] not in ('OFF', 'FINAL') and g.get('start')
            and datetime.datetime.fromisoformat(g['start'].replace('Z', '+00:00')) - now < datetime.timedelta(hours=36)]
    for day in sorted({g['date'] for g in soon}):
        mg = get(f"{MSF}/current/date/{day.replace('-', '')}/games.json", auth=MSF_KEY)
        if mg is None:
            continue
        MSF_OK = True
        for item in mg.get('games', []) or []:
            sc_ = item.get('schedule') or {}
            a, h = msf_abbr((sc_.get('awayTeam') or {}).get('abbreviation')), msf_abbr((sc_.get('homeTeam') or {}).get('abbreviation'))
            ours = next((g for g in soon if g['date'] == day and g['home'] == h and g['away'] == a), None) \
                or next((g for g in soon if g['date'] == day and g['home'] == h), None)
            if not ours or not sc_.get('id'):
                continue
            time.sleep(1.2)
            lu = get(f"{MSF}/current/games/{sc_['id']}/lineup.json", auth=MSF_KEY) or {}
            for tl in lu.get('teamLineups', []) or []:
                ab = msf_abbr((tl.get('team') or {}).get('abbreviation'))
                ab = ab if ab in (ours['home'], ours['away']) else None
                if not ab:
                    continue
                act = msf_goalie(((tl.get('actual') or {}).get('lineupPositions')))
                exp = msf_goalie(((tl.get('expected') or {}).get('lineupPositions')))
                if act:
                    msf_pick[(ours['id'], ab)] = {'name': act, 'status': 'Confirmed'}
                elif exp:
                    msf_pick[(ours['id'], ab)] = {'name': exp, 'status': 'Expected'}


if MSF_KEY and not MSF_OK and msf_pick == {}:
    MSF_STATUS = 'error'


def match_goalie(ab, name):
    n = norm(name)
    last = norm(name.split()[-1]) if name.split() else ''
    for g in teams[ab]['goalies']:
        if norm(g['name']) == n:
            return g
    cands = [g for g in teams[ab]['goalies'] if norm(g['name'].split()[-1]) == last]
    return cands[0] if len(cands) == 1 else None


OUT_STATUSES = {'IR', 'LTIR', 'Out', 'Suspended'}


def unavailable(ab, name):
    n = norm(name)
    for i in teams[ab]['injuries']:
        if norm(i['name']) == n and i['status'] in OUT_STATUSES:
            return i['status']
    return None


def project(ab, game):
    t = teams[ab]
    key = 'homeTeam' if game['home'] == ab else 'awayTeam'
    if game['state'] in ('LIVE', 'CRIT', 'OFF', 'FINAL'):
        s = starters(get(f"{WEB}/gamecenter/{game['id']}/boxscore")).get(key)
        if s:
            return {'id': s['id'], 'name': s['name'], 'status': 'Confirmed', 'why': 'Started the game.'}
    elif pregame_window(game):
        s = starters(boxcache(game['id']), require_flag=True).get(key)
        if s:
            return {'id': s['id'], 'name': s['name'], 'status': 'Confirmed',
                    'why': 'Named the starter in the official NHL game lineup.'}
    m = msf_pick.get((game['id'], ab))
    if m:
        gl_ = match_goalie(ab, m['name'])
        src = 'MySportsFeeds lists him in the starting lineup.' if m['status'] == 'Confirmed' else 'MySportsFeeds lists him as the expected starter.'
        return {'id': gl_['id'] if gl_ else None, 'name': gl_['name'] if gl_ else m['name'], 'status': m['status'], 'why': src}
    mo = manual.get((game['id'], ab))
    if mo:
        gl_ = match_goalie(ab, mo['name'])
        return {'id': gl_['id'] if gl_ else None, 'name': gl_['name'] if gl_ else mo['name'], 'status': mo['status'],
                'why': 'Confirmed by the team or reporters (entered on Five Hole).' if mo['status'] == 'Confirmed'
                else 'Expected to start, based on reports (entered on Five Hole).'}
    e = espn_prob.get((game['id'], ab))
    if e:
        gl_ = match_goalie(ab, e['name'])
        return {'id': gl_['id'] if gl_ else None, 'name': gl_['name'] if gl_ else e['name'], 'status': e['status'],
                'why': 'ESPN lists him as the confirmed starter.' if e['status'] == 'Confirmed' else 'ESPN lists him as the probable starter.'}
    return model_pick(ab, game)


HIST = {ab: [(x['date'], (x.get('goalie') or {}).get('id')) for x in reversed(t['last7'])] for ab, t in teams.items()}


def model_pick(ab, game):
    """Five Hole's own pick. Uses the team's recent starts in order, including this
    week's earlier projected games, so back-to-backs and tandems are handled."""
    t = teams[ab]
    hist = HIST[ab]
    healthy = [g for g in t['goalies'] if not unavailable(ab, g['name'])]
    out = [g['name'] for g in t['goalies'] if unavailable(ab, g['name'])]
    if not healthy:
        return None
    ids = {g['id'] for g in healthy}
    name = lambda gid: next((g['name'] for g in t['goalies'] if g['id'] == gid), 'the other goalie')
    recent = [gid for _, gid in hist[-10:] if gid]
    n = len(recent)
    share = {g['id']: (recent.count(g['id']) / n if n else 0) for g in healthy}
    ranked = sorted(healthy, key=lambda g: (-share[g['id']], -g['gs']))
    top = ranked[0]
    last_d, last_g = hist[-1] if hist else (None, None)
    try:
        b2b = bool(last_d) and datetime.date.fromisoformat(last_d) == datetime.date.fromisoformat(game['date']) - datetime.timedelta(days=1)
    except (ValueError, TypeError):
        b2b = False
    if b2b and last_g in ids and len(healthy) > 1:
        pick = sorted([g for g in healthy if g['id'] != last_g], key=lambda g: (-share[g['id']], -g['gs']))[0]
        why = f"Second night of a back-to-back, and {name(last_g)} is in net the night before."
    elif not n:
        pick = sorted(healthy, key=lambda g: -g['gs'])[0]
        why = 'Most starts this season.'
    elif share[top['id']] >= 0.65:
        pick = top
        why = f"Clear No. 1: started {recent.count(top['id'])} of the last {n} games."
    else:
        alt = [g for g in ranked if g['id'] != last_g and share[g['id']] >= 0.25]
        if last_g in ids and alt:
            pick = alt[0]
            why = (f"Close call. {pick['name']} and {name(last_g)} have split the net "
                   f"({recent.count(pick['id'])} and {recent.count(last_g)} of the last {n} starts), "
                   f"and {name(last_g)} had the previous game.")
        else:
            pick = top
            why = f"Started {recent.count(top['id'])} of the last {n} games."
    if out:
        why += ' ' + ', '.join(out) + (' is' if len(out) == 1 else ' are') + ' unavailable.'
    return {'id': pick['id'], 'name': pick['name'], 'status': 'Projected', 'why': why}



# ------------------------------------------------------ odds (ESPN game feed)
def odds_num(v):
    if v is None or v == '':
        return None
    if isinstance(v, (int, float)):
        return v
    t = str(v).strip().lower().lstrip('ou')
    if t in ('even', 'ev', 'pk', 'pick'):
        return 100
    try:
        f = float(t.replace('+', ''))
        return int(f) if f.is_integer() and abs(f) >= 20 else f
    except ValueError:
        return None


def pick_line(node):
    node = node or {}
    for k in ('current', 'close', 'open'):
        if isinstance(node.get(k), dict) and (node[k].get('odds') is not None or node[k].get('line') is not None):
            return node[k]
    return {}


def espn_odds(comp):
    lst = comp.get('odds') or []
    if not lst:
        return None
    o = lst[0]
    out = {'provider': (o.get('provider') or {}).get('name') or 'ESPN'}
    ml, ps, tot = o.get('moneyline') or {}, o.get('pointSpread') or {}, o.get('total') or {}
    hto, ato = o.get('homeTeamOdds') or {}, o.get('awayTeamOdds') or {}
    mh = odds_num(pick_line(ml.get('home')).get('odds')) or odds_num(hto.get('moneyLine'))
    ma = odds_num(pick_line(ml.get('away')).get('odds')) or odds_num(ato.get('moneyLine'))
    if mh is not None or ma is not None:
        out['ml'] = {'home': mh, 'away': ma}
    ph, pa = pick_line(ps.get('home')), pick_line(ps.get('away'))
    if ph or pa:
        out['pl'] = {'home': [odds_num(ph.get('line')), odds_num(ph.get('odds'))],
                     'away': [odds_num(pa.get('line')), odds_num(pa.get('odds'))]}
    elif o.get('spread') is not None:
        sp = odds_num(o.get('spread'))
        out['pl'] = {'home': [sp, odds_num(hto.get('spreadOdds'))], 'away': [-sp if sp is not None else None, odds_num(ato.get('spreadOdds'))]}
    ov, un = pick_line(tot.get('over')), pick_line(tot.get('under'))
    line = odds_num(ov.get('line')) or odds_num(un.get('line')) or odds_num(o.get('overUnder'))
    if line is not None:
        out['tot'] = {'line': line, 'over': odds_num(ov.get('odds')) or odds_num(o.get('overOdds')),
                      'under': odds_num(un.get('odds')) or odds_num(o.get('underOdds'))}
    return out if len(out) > 1 else None


ODDS_AT = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
espn_prob = {}   # (game id, team) -> {'name','status'}


def espn_goalie(c):
    for p in (dget(c, 'probables') or []):
        if not isinstance(p, dict):
            continue
        a = dget(p, 'athlete') or {}
        pos = dget(a, 'position')
        pos = dget(pos, 'abbreviation') if isinstance(pos, dict) else pos
        tag = ' '.join(str(x) for x in (dget(p, 'name'), dget(p, 'displayName'), dget(p, 'abbreviation'), pos)).lower()
        nm = dget(a, 'displayName') or dget(a, 'fullName')
        if ('goal' in tag or ' g' in f' {tag}') and nm:
            stv = dget(p, 'status')
            st = ' '.join(str(x) for x in ((dget(stv, 'name'), dget(stv, 'type')) if isinstance(stv, dict) else (stv,))).lower()
            return {'name': nm, 'status': 'Confirmed' if ('confirm' in st and 'unconfirm' not in st) else 'Expected'}
    return None


_box = {}


def boxcache(gid):
    if gid not in _box:
        _box[gid] = get(f'{WEB}/gamecenter/{gid}/boxscore')
    return _box[gid]


def pregame_window(game):
    if game['state'] == 'PRE':
        return True
    try:
        start = datetime.datetime.fromisoformat(game['start'].replace('Z', '+00:00'))
    except (ValueError, AttributeError, KeyError):
        return False
    mins = (start - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 60
    return -15 < mins < 75
def espn_event(day, ev):
    comp = (dget(ev, 'competitions') or [{}])[0]
    side = {}
    for c in dget(comp, 'competitors') or []:
        side[dget(c, 'homeAway')] = by_name.get(norm(dget(dget(c, 'team'), 'displayName')))
    g = next((x for x in games if x['date'] == day and x['home'] == side.get('home') and x['away'] == side.get('away')), None)
    if not g:
        return
    for c in dget(comp, 'competitors') or []:
        ab_ = side.get(dget(c, 'homeAway'))
        pg = espn_goalie(c)
        if ab_ and pg:
            espn_prob[(g['id'], ab_)] = pg
    try:
        od = espn_odds(comp)
    except Exception as e:  # noqa: BLE001
        WARN.append(f'ESPN odds skipped for {g["away"]}@{g["home"]}: {e!r}')
        od = None
    if od:
        od['updated'] = ODDS_AT
        g['odds'] = od


for day in sorted({g['date'] for g in games if g.get('date')}):
    sb = get(f"{ESPN_SB}?dates={day.replace('-', '')}") or {}
    for ev in dget(sb, 'events') or []:
        try:
            espn_event(day, ev)
        except Exception as e:  # noqa: BLE001
            WARN.append(f'ESPN event skipped on {day}: {e!r}')


# ------------------------------------------------ manual goalie overrides
# goalies.txt in the repository root. One line per goalie, for example:
#   PHI Joseph Woll                      (next PHI game, Confirmed)
#   PHI Joseph Woll expected             (next PHI game, Expected)
#   2026-10-28 PHI Dan Vladar confirmed  (a specific date)
manual = {}    # (game id, team) -> {'name', 'status'}
MANUAL_LINES = 0


def load_manual():
    global MANUAL_LINES
    path = os.path.join(ROOT, 'goalies.txt')
    if not os.path.exists(path):
        return
    for raw in open(path, encoding='utf-8'):
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        day = None
        if parts and len(parts[0]) == 10 and parts[0][4] == '-':
            day, parts = parts[0], parts[1:]
        if len(parts) < 2:
            continue
        ab = parts[0].upper()
        status = 'Confirmed'
        if parts[-1].lower() in ('confirmed', 'expected'):
            status = parts[-1].capitalize()
            parts = parts[:-1]
        name = ' '.join(parts[1:])
        if ab not in teams or not name:
            WARN.append(f'goalies.txt: could not read "{raw.strip()}"')
            continue
        mine = sorted([g for g in games if ab in (g['home'], g['away']) and g['state'] not in ('OFF', 'FINAL')],
                      key=lambda g: g.get('start') or g['date'])
        if day:
            mine = [g for g in mine if g['date'] == day]
        if not mine:
            continue
        manual[(mine[0]['id'], ab)] = {'name': name, 'status': status}
        MANUAL_LINES += 1

try:
    load_manual()
except Exception as e:  # noqa: BLE001
    WARN.append(f'goalies.txt skipped: {e!r}')
for g in sorted(games, key=lambda x: (x.get('start') or '', x.get('date') or '')):
    if g['away'] in teams and g['home'] in teams:
        picks = {}
        for side in ('away', 'home'):
            try:
                picks[side] = project(g[side], g)
            except Exception as e:  # noqa: BLE001
                WARN.append(f'goalie pick failed for {g[side]} on {g["date"]}: {e!r}')
                try:
                    picks[side] = model_pick(g[side], g)
                except Exception:  # noqa: BLE001
                    picks[side] = None
        g['goalies'] = picks
        for side in ('away', 'home'):
            ab_, p_ = g[side], g['goalies'][side]
            if p_ and not any(d == g['date'] for d, _ in HIST[ab_]):
                HIST[ab_].append((g['date'], p_.get('id')))

data = {
    'asOf': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
    'season': season, 'teams': teams, 'games': games, 'warnings': WARN[:20], 'msf': MSF_STATUS,
}
with open(OUT, 'w') as f:
    json.dump(data, f, separators=(',', ':'))
print(f'wrote {OUT}: {len(teams)} teams, {len(games)} games this week ({sum(1 for g in games if g.get("odds"))} with odds, {len(espn_prob)} ESPN probable goalies, {sum(1 for g in games for k in ('away', 'home') if (g.get('goalies') or {}).get(k) and g['goalies'][k]['why'].startswith('Named the starter'))} NHL lineup starters), {len(need)} box scores, MySportsFeeds {MSF_STATUS} ({len(msf_pick)} goalies), {MANUAL_LINES} manual goalies, {len(WARN)} warnings')
for w in WARN[:10]:
    print('  warning:', w)
