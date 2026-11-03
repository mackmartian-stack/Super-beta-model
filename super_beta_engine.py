"""Super Beta Model experimental prediction publisher.
Reads verified user-supplied normalized game/player data from data/input.json.
Never fabricates data or probabilities. Produces data/predictions.json.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / 'data' / 'input.json'
OUTPUT = ROOT / 'data' / 'predictions.json'


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Expected finite numeric statistic')
    return float(value)


def calculate_game(game):
    """Experimental logistic rating model; ratings must be derived from real data.
    Rating difference in points; 7 points maps to ~70% via logistic scale 8.0.
    Not calibrated and not a demonstrated betting edge.
    """
    home = number(game['home_rating'])
    away = number(game['away_rating'])
    advantage = number(game.get('home_advantage_points', 0))
    diff = home - away + advantage
    prob = 1 / (1 + math.exp(-max(-60, min(60, diff)) / 8.0))
    winner = game['home_team'] if prob >= .5 else game['away_team']
    return {
        'sport': game['sport'], 'game_id': game['game_id'],
        'date': game['date'], 'home_team': game['home_team'],
        'away_team': game['away_team'], 'predicted_winner': winner,
        'home_win_probability': round(prob, 4),
        'away_win_probability': round(1-prob, 4),
        'projected_home_margin': round(diff, 2),
        'confidence': 'uncalibrated', 'source': game['source'],
    }


def calculate_player(player):
    """Minutes/opportunities-based rate projection; no unverified injury adjustments."""
    baseline = number(player['per_opportunity_rate'])
    opportunities = number(player['projected_opportunities'])
    if baseline < 0 or opportunities < 0:
        raise ValueError('Rates and opportunities must be nonnegative')
    return {
        'sport': player['sport'], 'player': player['player'],
        'team': player['team'], 'stat': player['stat'],
        'projection': round(baseline * opportunities, 2),
        'date': player['date'], 'source': player['source'],
        'confidence': 'uncalibrated',
    }


def main():
    output = {'model': 'Super Beta Model 2.0', 'status': 'awaiting_verified_input',
              'generated_at': datetime.now(timezone.utc).isoformat(),
              'experimental': True, 'calibrated': False,
              'note': 'No proven betting edge. Inputs must be verified and dated.',
              'team_predictions': [], 'player_predictions': [], 'errors': []}
    if INPUT.exists():
        raw = json.loads(INPUT.read_text(encoding='utf-8'))
        for item in raw.get('games', []):
            try:
                if item['sport'] not in ('NFL', 'NBA', 'CFB'):
                    raise ValueError('Unknown sport')
                output['team_predictions'].append(calculate_game(item))
            except (KeyError, TypeError, ValueError) as exc:
                output['errors'].append(f"Game {item.get('game_id', '?')}: {exc}")
        for item in raw.get('players', []):
            try:
                if item['sport'] not in ('NFL', 'NBA', 'CFB'):
                    raise ValueError('Unknown sport')
                output['player_predictions'].append(calculate_player(item))
            except (KeyError, TypeError, ValueError) as exc:
                output['errors'].append(f"Player {item.get('player', '?')}: {exc}")
        output['team_predictions'].sort(key=lambda g: abs(g['home_win_probability']-.5), reverse=True)
        output['player_predictions'].sort(key=lambda p: p['projection'], reverse=True)
        output['team_predictions'] = output['team_predictions'][:12]
        output['player_predictions'] = output['player_predictions'][:12]
        output['status'] = 'predictions_available' if (output['team_predictions'] or output['player_predictions']) else 'awaiting_verified_input'
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8')
    print(f"Published {len(output['team_predictions'])} games and {len(output['player_predictions'])} players; {len(output['errors'])} errors")

if __name__ == '__main__':
    main()
