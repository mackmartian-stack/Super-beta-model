"""Archive prior forecasts and score settled games without retroactive predictions."""
import json
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'

def read(name, fallback):
    p = DATA / name
    try:
        return json.loads(p.read_text()) if p.exists() else fallback
    except (ValueError, OSError):
        return fallback

def main():
    DATA.mkdir(exist_ok=True)
    history = read('prediction_history.json', {'games': {}, 'players': {}, 'created_at': datetime.now(timezone.utc).isoformat()})
    old = read('predictions.json', {})
    # Archive existing forecasts BEFORE running the engine; never overwrite the first prediction for a game.
    for g in old.get('team_predictions', []):
        key = str(g.get('sport', '')) + ':' + str(g.get('game_id', ''))
        if g.get('game_id') and key not in history['games']:
            history['games'][key] = {'forecast': g, 'first_recorded_at': old.get('generated_at'), 'result': None}
    schedule = read('schedule.json', {})
    settled = 0
    for g in schedule.get('games', []):
        key = str(g.get('sport', '')) + ':' + str(g.get('game_id', ''))
        item = history['games'].get(key)
        if not item or item.get('result') or g.get('status') != 'STATUS_FINAL':
            continue
        # schedule.json omits scores; ratings collector includes results only internally.
        # Don't infer a winner from schedules. Results can be supplied via results.json.
    results = read('results.json', {'games': []})
    for g in results.get('games', []):
        key = str(g.get('sport', '')) + ':' + str(g.get('game_id', ''))
        item = history['games'].get(key)
        if not item or item.get('result'):
            continue
        h, a = g.get('home_score'), g.get('away_score')
        if g.get('status') != 'STATUS_FINAL' or not isinstance(h, (int, float)) or not isinstance(a, (int, float)):
            continue
        p = item['forecast']
        predicted_home = p.get('predicted_winner') == p.get('home_team')
        actual_home = h > a
        if h == a:
            continue
        item['result'] = {'home_score': h, 'away_score': a, 'correct_winner': predicted_home == actual_home,
                          'actual_home_win': actual_home, 'settled_at': datetime.now(timezone.utc).isoformat()}
        settled += 1
    complete = [v for v in history['games'].values() if v.get('result')]
    metrics = {'recorded_forecasts': len(history['games']), 'settled_games': len(complete),
               'winner_accuracy': round(sum(v['result']['correct_winner'] for v in complete) / len(complete), 4) if complete else None,
               'note': 'Accuracy on tracked games only; not out-of-sample calibration or betting ROI.'}
    (DATA / 'prediction_history.json').write_text(json.dumps(history, indent=2) + '\n')
    (DATA / 'accuracy.json').write_text(json.dumps(metrics, indent=2) + '\n')
    print(f'Tracking {len(history["games"])} games; settled {len(complete)} (new {settled})')

if __name__ == '__main__':
    main()
