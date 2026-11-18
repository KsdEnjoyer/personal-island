"""Deterministic local weather fixture shared by UI tests."""
import time
def fixture():
    now=int(time.time())
    start=now//3600*3600
    day=(now+3*3600)//86400*86400-3*3600
    return {'data':{'city':'Санкт-Петербург','fetched_at':now,
        'current':{'time':now,'temperature_2m':-1.5,'apparent_temperature':-5.0,'relative_humidity_2m':84,'is_day':0,'weather_code':71,'wind_speed_10m':4.2,'wind_direction_10m':315,'precipitation':.3},
        'hourly':[{'time':start+i*3600,'temperature':-1.5+i*.4,'precipitation':max(0,70-i*10),'code':71 if i<3 else 3,'is_day':False} for i in range(8)],
        'daily':[{'time':day+i*86400,'low':-4+i,'high':2+i,'code':71 if i<2 else 3,'precipitation':1.2 if i<3 else 0,'sunrise':day+i*86400+9*3600,'sunset':day+i*86400+16*3600} for i in range(7)]},'stale':False,'error':None}
