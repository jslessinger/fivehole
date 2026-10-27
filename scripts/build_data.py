#!/usr/bin/env python3
"""Rebuild data.json for Five Hole from nflverse's free public data.

Downloads this season's weekly player stats, play-by-play (to strip kneel-downs),
injury reports, weekly rosters, depth charts and the schedule, then writes
data.json next to index.html. Run it from the repository root:

    python scripts/build_data.py
"""
import os, sys, json, datetime, tempfile, urllib.request
import pandas as pd

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT=os.path.join(ROOT,'data.json')
today=datetime.date.today()
SEASON=int(os.environ.get('SEASON') or (today.year if today.month>=8 else today.year-1))
AS_OF=today.strftime('%b %-d, %Y')
REL='https://github.com/nflverse/nflverse-data/releases/download'
FILES={
  'w.csv':f'{REL}/stats_player/stats_player_week_{SEASON}.csv',
  'pbp.csv.gz':f'{REL}/pbp/play_by_play_{SEASON}.csv.gz',
  'inj.csv':f'{REL}/injuries/injuries_{SEASON}.csv',
  'ros.csv':f'{REL}/weekly_rosters/roster_weekly_{SEASON}.csv',
  'dc.csv':f'{REL}/depth_charts/depth_charts_{SEASON}.csv',
  'games.csv':'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv',
}
tmp=tempfile.mkdtemp()
os.chdir(tmp)
for name,url in FILES.items():
    print('downloading',url,flush=True)
    req=urllib.request.Request(url,headers={'User-Agent':'fivehole-builder'})
    with urllib.request.urlopen(req,timeout=300) as r, open(name,'wb') as f:
        f.write(r.read())

d=pd.read_csv('w.csv',low_memory=False).copy()
# remove kneel-downs
p=pd.read_csv('pbp.csv.gz',usecols=['week','qb_kneel','rusher_player_id','rushing_yards'],low_memory=False)
k=p[p.qb_kneel==1].groupby(['rusher_player_id','week']).agg(kc=('qb_kneel','size'),ky=('rushing_yards','sum')).reset_index()
d=d.merge(k,how='left',left_on=['player_id','week'],right_on=['rusher_player_id','week'])
d['kc']=d.kc.fillna(0); d['ky']=d.ky.fillna(0)
print('kneels removed:',int(d.kc.sum()),'of',len(p[p.qb_kneel==1]),'yards',d.ky.sum())
d['carries']=d.carries.fillna(0)-d.kc; d['rushing_yards']=d.rushing_yards.fillna(0)-d.ky
d['pos']=d.position.replace({'FB':'RB','HB':'RB'})
d=d[d.pos.isin(['QB','RB','WR','TE'])].fillna(0).copy()
wr=d[d.pos=='WR'].copy()
wr=wr.join(wr.groupby(['team','player_display_name']).targets.sum().rename('st'),on=['team','player_display_name'])
# depth-chart snapshots: rank in effect on game day
dc=pd.read_csv('dc.csv',low_memory=False); dc['day']=dc.dt.str[:10]
dc=dc[dc.pos_abb.isin(['WR','RB','TE','QB'])].groupby(['day','team','pos_abb','gsis_id']).pos_rank.min().reset_index()
DAYS=sorted(dc.day.unique())
_gs=pd.read_csv('games.csv');_gs=_gs[(_gs.season==SEASON)&(_gs.game_type=='REG')]
gday={}
for r in _gs.itertuples(): gday[(r.week,r.home_team)]=r.gameday; gday[(r.week,r.away_team)]=r.gameday
import bisect
_dcidx={k:dict(zip(v.gsis_id,v.pos_rank)) for k,v in dc.groupby(['day','team','pos_abb'])}
def depth(day,team,pos):
    i=bisect.bisect_right(DAYS,day)-1
    while i>=0:
        m=_dcidx.get((DAYS[i],team,pos))
        if m: return m
        i-=1
    return {}
wr['dr']=[depth(gday.get((w,t),f'{SEASON+1}-12-31'),t,'WR').get(pid,999) for w,t,pid in zip(wr.week,wr.team,wr.player_id)]
wr=wr.sort_values(['team','week','dr','st'],ascending=[True,True,True,False])
wr['role']=(wr.groupby(['team','week']).cumcount()+1).clip(upper=3)
def agg(key):
    out={}
    for (t,w),x in d.groupby([key,'week']):
        r=x[x.pos=='RB'];wx=x[x.pos=='WR'];te=x[x.pos=='TE'];qb=x[x.pos=='QB']
        v=[r.rushing_yards.sum(),r.carries.sum(),r.rushing_tds.sum(),r.receiving_yards.sum(),r.receptions.sum(),r.receiving_tds.sum(),
           wx.receiving_yards.sum(),wx.receptions.sum(),wx.targets.sum(),wx.receiving_tds.sum(),
           te.receiving_yards.sum(),te.receptions.sum(),te.targets.sum(),te.receiving_tds.sum(),qb.rushing_yards.sum()]
        ww=wr[(wr[key]==t)&(wr.week==w)]
        for ro in (1,2,3):
            y=ww[ww.role==ro]; v+=[y.receiving_yards.sum(),y.receptions.sum(),y.targets.sum(),y.receiving_tds.sum()]
        v.append(qb.carries.sum())
        # QB passing (indexes 28-32): yards, attempts, completions, TDs, interceptions
        v+=[qb.passing_yards.sum(),qb.attempts.sum(),qb.completions.sum(),qb.passing_tds.sum(),qb.passing_interceptions.sum()]
        out.setdefault(t,{})[int(w)]=[int(round(a)) for a in v]
    return out
de=agg('opponent_team'); of=agg('team')
players={}
s=d.groupby(['team','pos','player_id','player_display_name']).agg(g=('week','nunique'),ry=('rushing_yards','sum'),cy=('receiving_yards','sum'),c=('carries','sum'),rec=('receptions','sum'),tg=('targets','sum'),
  py=('passing_yards','sum'),pa=('attempts','sum'),pc=('completions','sum'),ptd=('passing_tds','sum'),pint=('passing_interceptions','sum')).reset_index()
s['tot']=s.ry+s.cy
TODAY=DAYS[-1]
_ros=pd.read_csv('ros.csv',low_memory=False); _ros=_ros[_ros.week==_ros.groupby('team').week.transform('max')]
rname=dict(zip(_ros.gsis_id,_ros.full_name))
for t in sorted(d.team.unique()):
    for po in ['QB','RB','WR','TE']:
        x=s[(s.team==t)&(s.pos==po)].copy()
        cur=depth(TODAY,t,po)
        x['dr']=x.player_id.map(lambda p:cur.get(p,999))
        # depth-chart players with no stats for this team yet
        extra=[(pid,rk) for pid,rk in cur.items() if pid not in set(x.player_id) and rk<= {'QB':1,'RB':2,'WR':3,'TE':1}[po]]
        for pid,rk in extra:
            x=pd.concat([x,pd.DataFrame([{'team':t,'pos':po,'player_id':pid,'player_display_name':rname.get(pid,pid),'g':0,'ry':0,'cy':0,'c':0,'rec':0,'tg':0,'py':0,'pa':0,'pc':0,'ptd':0,'pint':0,'tot':0,'dr':rk}])])
        x=x.sort_values(['dr',{'WR':'tg','QB':'pa'}.get(po,'tot')],ascending=[True,False]).head({'QB':3,'WR':7,'RB':5,'TE':4}[po])
        # [name, games, rushYds, recYds, carries, rec, targets, id, depth, passYds, att, cmp, passTD, int]
        players.setdefault(t,{})[po]=[[n,int(g),int(ry),int(cy),int(c),int(rec),int(tg),pid,int(dr),int(py),int(pa),int(pc),int(ptd),int(pint)]
            for pid,n,g,ry,cy,c,rec,tg,dr,py,pa,pc,ptd,pint in x[['player_id','player_display_name','g','ry','cy','c','rec','tg','dr','py','pa','pc','ptd','pint']].values]
# availability for current week
gs=pd.read_csv('games.csv');gs=gs[(gs.season==SEASON)&(gs.game_type=='REG')]
_left=gs[gs.home_score.isna()]
CUR=int(_left.week.min()) if len(_left) else int(gs.week.max())
inj=pd.read_csv('inj.csv'); inj=inj[(inj.week==CUR)&inj.report_status.notna()]
ros=pd.read_csv('ros.csv',low_memory=False)
# nflverse's weekly roster file sometimes lags for a few teams, so use each team's own latest week
ros=ros[ros.week==ros.groupby('team').week.transform('max')]
rteam=dict(zip(ros.gsis_id,ros.team)); rstat=dict(zip(ros.gsis_id,ros.status))
ROS_TEAMS=set(ros.team)
ROS_CURRENT=set(ros[ros.week==ros.week.max()].team)  # teams whose roster is up to date
istat=dict(zip(inj.gsis_id,inj.report_status)); iinj=dict(zip(inj.gsis_id,inj.report_primary_injury.fillna('')))
status={}
for t,P in players.items():
    for po,lst in P.items():
        for p in lst:
            pid=p[7]; st=None
            if rstat.get(pid)=='RES': st='IR'
            elif pid in rteam and rteam[pid]!=t: st='Traded'
            elif rstat.get(pid) in ('CUT','RET') or (pid not in rteam and t in ROS_TEAMS): st='Released'
            elif rstat.get(pid) in ('INA','DEV','EXE','TRT') and t in ROS_CURRENT: st='Inactive'
            if pid in istat and st not in ('IR','Traded','Released'): st=istat[pid]
            if st: status[pid]=[st,iinj.get(pid,'')]
dinj={}
dpos={'CB':'DB','S':'DB','SAF':'DB','DB':'DB','FS':'DB','SS':'DB','LB':'LB','ILB':'LB','OLB':'LB','MLB':'LB','DE':'DL','DT':'DL','NT':'DL','DL':'DL'}
for r in inj.itertuples():
    if r.position in dpos:
        dinj.setdefault(r.team,[]).append([r.full_name,r.position,dpos[r.position],r.report_status,'' if pd.isna(r.report_primary_injury) else r.report_primary_injury])
g=pd.read_csv('games.csv');g=g[(g.season==SEASON)&(g.game_type=='REG')]
data={'asOf':AS_OF,'season':SEASON,'throughWeek':int(d.week.max()),'def':de,'off':of,'players':players,'status':status,'dinj':dinj,'injWeek':CUR,
 'schedule':[[int(r.week),r.gameday,r.away_team,r.home_team,None if pd.isna(r.home_score) else [int(r.away_score),int(r.home_score)],r.gametime] for r in g.itertuples()]}
json.dump(data,open('data.json','w'),separators=(',',':'))

logr={}
def nm(n): return n.replace('.', '. ',1) if '. ' not in n else n
for (t,w),x in d.groupby(['opponent_team','week']):
    ru=x[(x.pos.isin(['RB','QB']))&(x.carries>0)].copy()
    ru['o']=ru.pos.map({'RB':0,'QB':1})
    ru=ru.sort_values(['o','rushing_yards'],ascending=[True,False])
    ww=wr[(wr.opponent_team==t)&(wr.week==w)&(wr.targets>0)][['player_name','role','targets','receptions','receiving_yards','receiving_tds']].copy()
    ww['lab']=ww.role.map({1:'WR1',2:'WR2',3:'WR3+'})
    ot=x[(x.pos.isin(['RB','TE']))&(x.targets>0)][['player_name','pos','targets','receptions','receiving_yards','receiving_tds']].copy().rename(columns={'pos':'lab'})
    re=pd.concat([ot,ww.drop(columns='role')])
    re['o']=re.lab.map({'RB':0,'WR1':1,'WR2':2,'WR3+':3,'TE':4})
    re=re.sort_values(['o','receiving_yards'],ascending=[True,False])
    pa=x[(x.pos=='QB')&(x.attempts>0)].sort_values('attempts',ascending=False)
    logr.setdefault(t,{})[int(w)]={
      'pa':[[nm(r.player_name),int(r.attempts),int(r.completions),int(round(r.passing_yards)),int(r.passing_tds),int(r.passing_interceptions)] for r in pa.itertuples()],
      'ru':[[nm(r.player_name),r.pos,int(r.carries),int(round(r.rushing_yards)),int(r.rushing_tds)] for r in ru.itertuples()],
      're':[[nm(r.player_name),r.lab,int(r.targets),int(r.receptions),int(r.receiving_yards),int(r.receiving_tds)] for r in re.itertuples()]}
data['logr']=logr


with open(OUT,'w') as f:
    json.dump(data,f,separators=(',',':'))
print(f'wrote {OUT}: season {SEASON}, through week {data["throughWeek"]}, injury week {CUR}, as of {AS_OF}')
