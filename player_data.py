"""Experimental player per-game baselines from ESPN public boxscores.
No lineups/injury verification, no minutes/usage forecasts. Skip insufficient samples.
"""
import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
PATHS = {'NBA': 'basketball/nba', 'NFL': 'football/nfl', 'CFB': 'football/college-football'}
LIMIT = int(os.getenv('SB_BOXSCORE_LIMIT', '36'))
MIN_SAMPLE = 1

def fetch(url):
    req = Request(url, headers={'User-Agent': 'SuperBetaPersonalResearch/3.0', 'Accept': 'application/json'})
    with urlopen(req, timeout=18) as response:
        return json.load(response)

def num(v, made=False):
    if v is None or v == '--':
        return None
    try:
        if '-' in str(v) and made:
            return float(str(v).split('-')[0])
        return float(str(v).replace(',', ''))
    except (ValueError, TypeError):
        return None

def parse_boxscore(payload, sport):
    out = []
    box = (payload.get('boxscore') or {}).get('players') or []
    for team_entry in box:
        team = (team_entry.get('team') or {}).get('displayName')
        if not team:
            continue
        for group in team_entry.get('statistics') or []:
            labels = [str(x).upper().replace(' ', '') for x in group.get('labels') or []]
            name = str(group.get('name') or '').lower()
            for athlete_entry in group.get('athletes') or []:
                athlete = athlete_entry.get('athlete') or {}
                player = athlete.get('displayName')
                athlete_id = str(athlete.get('id') or '')
                if not player or not athlete_id or athlete_entry.get('didNotPlay'):
                    continue
                values = athlete_entry.get('stats') or []
                if len(values) != len(labels):
                    continue
                stats = dict(zip(labels, values))
                metrics = {}
                if sport == 'NBA':
                    for key, output in [('PTS', 'points'), ('REB', 'rebounds'), ('AST', 'assists')]:
                        if key in stats:
                            metrics[output] = num(stats[key])
                    if '3PT' in stats:
                        metrics['three_pointers_made'] = num(stats['3PT'], made=True)
                    elif '3PM' in stats:
                        metrics['three_pointers_made'] = num(stats['3PM'])
                else:
                    # ESPN football group names and labels differ by competition.
                    if 'passing' in name:
                        for key in ('YDS', 'PASSYDS'):
                            if key in stats:
                                metrics['passing_yards'] = num(stats[key]); break
                    if 'rushing' in name and 'YDS' in stats:
                        metrics['rushing_yards'] = num(stats['YDS'])
                    if 'receiving' in name and 'YDS' in stats:
                        metrics['receiving_yards'] = num(stats['YDS'])
                for metric, value in metrics.items():
                    if value is not None and value >= 0:
                        out.append((sport, team, athlete_id, player, metric, value))
    return out

def main():
    schedule_path = DATA / 'schedule.json'
    input_path = DATA / 'input.json'
    if not schedule_path.exists() or not input_path.exists():
        raise RuntimeError('Run collect_data.py before player_data.py')
    schedule = json.loads(schedule_path.read_text())
    inputs = json.loads(input_path.read_text())
    now = datetime.now(timezone.utc)
    completed = []
    for game in schedule.get('games', []):
        try:
            dt = datetime.fromisoformat(game['date'].replace('Z', '+00:00'))
        except (ValueError, TypeError, AttributeError):
            continue
        if game.get('status') == 'STATUS_FINAL' and now - timedelta(days=32) <= dt <= now:
            completed.append(game)
    completed.sort(key=lambda x: x['date'], reverse=True)
    # Rotate sports fairly, prioritize most recent games.
    selected = []
    by_sport = {sport: [g for g in completed if g['sport'] == sport] for sport in PATHS}
    while len(selected) < LIMIT and any(by_sport.values()):
        for sport in PATHS:
            if by_sport[sport] and len(selected) < LIMIT:
                selected.append(by_sport[sport].pop(0))
    observations = defaultdict(dict)
    errors = []
    for g in selected:
        sport = g['sport']
        url = f"https://site.api.espn.com/apis/site/v2/sports/{PATHS[sport]}/summary?{urlencode({'event': g['game_id']})}"
        try:
            for sp, team, aid, player, metric, value in parse_boxscore(fetch(url), sport):
                observations[(sp, team, aid, player, metric)][g['game_id']] = value
        except Exception as exc:
            errors.append(f"{sport} {g['game_id']}: {type(exc).__name__}: {str(exc)[:90]}")
        time.sleep(.12)
    future = inputs.get('games', [])
    upcoming = {(g['sport'], team): g for g in future for team in (g['home_team'], g['away_team'])}
    results = []
    for (sport, team, aid, player, metric), game_values in observations.items():
        if (sport, team) not in upcoming or len(game_values) < MIN_SAMPLE:
            continue
        values = list(game_values.values())
        # Mean per appearance, not a true opportunity-adjusted forecast.
        baseline = sum(values) / len(values)
        game = upcoming[(sport, team)]
        results.append({'sport': sport, 'player': player, 'team': team, 'stat': metric,
                        'per_opportunity_rate': round(baseline, 4), 'projected_opportunities': 1,
                        'date': game['date'], 'source': 'ESPN public game boxscores (unofficial)',
                        'sample_games': len(values), 'method': 'mean of available recent appearances; no minutes/injury adjustment'})
    inputs['players'] = results
    inputs.setdefault('warnings', []).append('Player projections are unadjusted recent per-game averages, not injury/lineup/usage-adjusted forecasts.')
    input_path.write_text(json.dumps(inputs, indent=2) + '\n')
    (DATA / 'player_collection.json').write_text(json.dumps({'boxscores_requested': len(selected), 'eligible_player_metrics': len(results), 'errors': errors}, indent=2) + '\n')
    print(f'Player collection: {len(selected)} boxscores, {len(results)} eligible metrics, {len(errors)} errors')

if __name__ == '__main__':
    main()
