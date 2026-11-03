"""Super Beta: collect dated ESPN public scoreboards, derive transparent ratings.
Unofficial endpoints may change. No fabricated player/injury data.
"""
import json, math, os, time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
LEAGUES = {'NFL': 'football/nfl', 'NBA': 'basketball/nba', 'CFB': 'football/college-football'}
HISTORY_DAYS = int(os.getenv('SB_HISTORY_DAYS', '65'))
FUTURE_DAYS = int(os.getenv('SB_FUTURE_DAYS', '7'))
MIN_GAMES = {'NBA': 5, 'NFL': 3, 'CFB': 3}


def fetch(url, retries=2):
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={'User-Agent': 'SuperBetaPersonalResearch/2.2', 'Accept': 'application/json'})
            with urlopen(req, timeout=22) as r:
                return json.load(r)
        except Exception:
            if attempt == retries:
                raise
            time.sleep(1.5 * (attempt + 1))


def scoreboard(sport, day):
    params = {'dates': day.strftime('%Y%m%d'), 'limit': 500}
    if sport == 'CFB':
        params['groups'] = '80'  # FBS grouping; provider may change this mapping
    url = f"https://site.api.espn.com/apis/site/v2/sports/{LEAGUES[sport]}/scoreboard?{urlencode(params)}"
    return fetch(url), url


def parse_event(event, sport, source):
    comps = (event.get('competitions') or [{}])[0]
    competitors = comps.get('competitors') or []
    sides = {c.get('homeAway'): c for c in competitors}
    if not sides.get('home') or not sides.get('away'):
        return None
    home, away = sides['home'], sides['away']
    def name(c):
        t = c.get('team') or {}
        return t.get('displayName') or t.get('name')
    def score(c):
        try:
            return float(c.get('score'))
        except (ValueError, TypeError):
            return None
    status = (event.get('status') or {}).get('type') or {}
    finished = bool(status.get('completed')) or status.get('name') == 'STATUS_FINAL'
    return {'sport': sport, 'game_id': str(event.get('id', '')), 'date': event.get('date'),
            'home_team': name(home), 'away_team': name(away),
            'home_score': score(home), 'away_score': score(away),
            'final': finished, 'status': status.get('name'), 'source': source}


def ratings(games, sport):
    completed = sorted((g for g in games if g['sport'] == sport and g['final'] and
                        g['home_score'] is not None and g['away_score'] is not None), key=lambda x: x['date'])
    teams = defaultdict(list)
    for g in completed:
        h, a = g['home_team'], g['away_team']
        teams[h].append((g['home_score'], g['away_score'], a, 1))
        teams[a].append((g['away_score'], g['home_score'], h, -1))
    # Recency-weighted scoring margin, adjusted iteratively for opponent strength.
    base = {}
    for team, rows in teams.items():
        recent = rows[-12:]
        weights = list(range(1, len(recent) + 1))
        base[team] = sum(w * (pf - pa) for w, (pf, pa, _, _) in zip(weights, recent)) / sum(weights)
    adjusted = base.copy()
    for _ in range(3):
        new = {}
        for team, rows in teams.items():
            recent = rows[-12:]
            weights = list(range(1, len(recent) + 1))
            sos = sum(w * adjusted.get(opp, 0) for w, (_, _, opp, _) in zip(weights, recent)) / sum(weights)
            new[team] = 0.8 * base[team] + 0.2 * sos
        adjusted = new
    # Convert margin to engine rating scale: engine maps 7 rating points to ~7 expected points.
    return {team: {'rating': round(100 + margin, 3), 'games': len(rows),
                   'avg_scored': round(sum(x[0] for x in rows[-12:]) / len(rows[-12:]), 2),
                   'avg_allowed': round(sum(x[1] for x in rows[-12:]) / len(rows[-12:]), 2)}
            for team, rows in teams.items() for margin in [adjusted[team]]}


def main():
    DATA.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    all_games, errors, seen = [], [], set()
    # Limit historical request volume: NBA daily; football 7-day intervals plus recent dates.
    for sport in LEAGUES:
        if sport == 'NBA':
            offsets = range(-HISTORY_DAYS, FUTURE_DAYS + 1)
        else:
            offsets = sorted(set(list(range(-HISTORY_DAYS, FUTURE_DAYS + 1, 7)) + list(range(-7, FUTURE_DAYS + 1))))
        for offset in offsets:
            day = (now + timedelta(days=offset)).date()
            try:
                payload, url = scoreboard(sport, day)
                for event in payload.get('events', []):
                    game = parse_event(event, sport, url)
                    if game and game['game_id'] and (sport, game['game_id']) not in seen:
                        seen.add((sport, game['game_id']))
                        all_games.append(game)
            except Exception as exc:
                errors.append(f'{sport} {day.isoformat()}: {type(exc).__name__}: {str(exc)[:100]}')
            time.sleep(0.12)
    all_games.sort(key=lambda g: (g['date'] or '', g['sport']))
    strengths = {sport: ratings(all_games, sport) for sport in LEAGUES}
    inputs = {'games': [], 'players': [], 'generated_at': now.isoformat(),
              'method': 'Recent scoring margin plus opponent-strength adjustment; experimental, uncalibrated',
              'warnings': ['No verified injuries, lineups, coaching adjustments, or player projections.']}
    schedule = []
    for g in all_games:
        schedule.append({k: g[k] for k in ('sport', 'game_id', 'date', 'home_team', 'away_team', 'status', 'source')})
        if g['final'] or not g['date'] or not (now <= datetime.fromisoformat(g['date'].replace('Z', '+00:00')) <= now + timedelta(days=FUTURE_DAYS)):
            continue
        s = g['sport']
        h, a = strengths[s].get(g['home_team']), strengths[s].get(g['away_team'])
        if not h or not a or min(h['games'], a['games']) < MIN_GAMES[s]:
            continue
        inputs['games'].append({'sport': s, 'game_id': g['game_id'], 'date': g['date'],
                                'home_team': g['home_team'], 'away_team': g['away_team'],
                                'home_rating': h['rating'], 'away_rating': a['rating'],
                                'home_advantage_points': {'NBA': 2.0, 'NFL': 1.5, 'CFB': 2.5}[s],
                                'source': g['source']})
    (DATA / 'schedule.json').write_text(json.dumps({'collected_at': now.isoformat(), 'games': schedule, 'errors': errors}, indent=2) + '\n')
    (DATA / 'input.json').write_text(json.dumps(inputs, indent=2) + '\n')
    (DATA / 'ratings.json').write_text(json.dumps({'generated_at': now.isoformat(), 'ratings': strengths,
                                                  'errors': errors}, indent=2) + '\n')
    print(f'Collected {len(all_games)} games; eligible future games: {len(inputs["games"])}; errors: {len(errors)}')
    if errors:
        print('First collection error:', errors[0])
    if not all_games and errors:
        raise RuntimeError('No scoreboards retrieved; refusing to replace previous data with empty feed')
    # Save verified final scores for prediction accuracy tracking.
    completed_results = []

    for game in all_games:
        if (
            game.get('final')
            and game.get('home_score') is not None
            and game.get('away_score') is not None
        ):
            completed_results.append({
                'sport': game['sport'],
                'game_id': game['game_id'],
                'date': game['date'],
                'home_team': game['home_team'],
                'away_team': game['away_team'],
                'home_score': game['home_score'],
                'away_score': game['away_score'],
                'status': 'STATUS_FINAL',
                'source': game['source']
            })

    results_file = DATA / 'results.json'

    results_file.write_text(
        json.dumps({
            'generated_at': now.isoformat(),
            'games': completed_results
        }, indent=2) + '\n'
    )

    print(f'Saved {len(completed_results)} completed game results')
if __name__ == '__main__':
    main()
