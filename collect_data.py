"""Collect public ESPN scoreboard summaries. No fabricated statistics."""
import json, os, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parent
LEAGUES={'NFL':'football/nfl','NBA':'basketball/nba','CFB':'football/college-football'}
def fetch(url):
 req=urllib.request.Request(url,headers={'User-Agent':'SuperBetaModel/2.1 (personal research)','Accept':'application/json'})
 with urllib.request.urlopen(req,timeout=25) as r:return json.load(r)
def main():
 games=[]; errors=[]; now=datetime.now(timezone.utc)
 for sport,path in LEAGUES.items():
  for day in (now.date()+timedelta(days=i) for i in range(0,4)):
   try:
    url=f'https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={day:%Y%m%d}&limit=200'
    payload=fetch(url)
    for event in payload.get('events',[]):
     comp=(event.get('competitions') or [{}])[0]; teams=comp.get('competitors',[])
     home=next((t for t in teams if t.get('homeAway')=='home'),None)
     away=next((t for t in teams if t.get('homeAway')=='away'),None)
     if not home or not away:continue
     games.append({'sport':sport,'game_id':str(event.get('id')),'date':event.get('date'), 'home_team':home.get('team',{}).get('displayName'), 'away_team':away.get('team',{}).get('displayName'),'status':event.get('status',{}).get('type',{}).get('name'),'source':url})
   except Exception as exc:errors.append(f'{sport} {day}: {type(exc).__name__}: {exc}')
 out={'collected_at':now.isoformat(),'source':'ESPN public scoreboard endpoints (unofficial; availability may change)','games':list({(g['sport'],g['game_id']):g for g in games}.values()),'players':[],'errors':errors,'notes':['Schedule-only collection. Ratings, player rates, injury status and probabilities are NOT supplied.','No predictions are made without independently validated statistical inputs.']}
 (ROOT/'data').mkdir(exist_ok=True)
 (ROOT/'data'/'schedule.json').write_text(json.dumps(out,indent=2)+'\n')
 print(f'Collected {len(out["games"])} scheduled events, {len(errors)} fetch errors')
if __name__=='__main__':main()
