from __future__ import annotations
import logging, os, time
import db
from matching import score_listing
from telegram import send_telegram, format_match_message
from scrapers.registry import get_scraper
from scrapers.models import SearchParams

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(name)s %(levelname)s %(message)s')
log=logging.getLogger('worker')
POLL_INTERVAL_SECONDS=max(30,int(os.getenv('POLL_INTERVAL_SECONDS','300')))
MIN_NOTIFY_SCORE=max(0,min(100,int(os.getenv('MIN_NOTIFY_SCORE','75'))))

def _locations(profile):
    raw=profile.get('districts') or ''
    vals=[x.strip() for x in raw.replace(';',',').split(',') if x.strip()]
    if vals:return vals
    if 'BE' in (profile.get('regions') or []):return ['Berlin']
    return []

def build_jobs(profiles):
    jobs={}
    for p in profiles:
        regions=tuple(sorted(p.get('regions') or ['DE']))
        locations=tuple(sorted(_locations(p)))
        for source in p.get('sources') or []:
            key=(source,regions,locations)
            jobs.setdefault(key,set()).add(p['id'])
    return jobs

def process_listing(item,profiles_by_id,profile_ids):
    listing_id,is_new=db.upsert_listing(item)
    for pid in profile_ids:
        p=profiles_by_id[pid]
        result=score_listing(item.__dict__,p)
        if not result:continue
        score,components,reasons=result
        first=db.save_match(listing_id,pid,score,components,reasons)
        if first and score>=MIN_NOTIFY_SCORE:
            msg=format_match_message(p['name'],score,item.title,item.price or item.price_total,item.rooms,item.size,item.address,item.url,item.source)
            if send_telegram(msg): db.mark_notified(listing_id,pid)

def run_once():
    profiles=db.get_active_profiles_with_sources()
    if not profiles:return {'jobs':0,'listings':0}
    lock=db.try_scan_lock()
    if not lock:
        log.warning('Scan bereits durch einen anderen Prozess gesperrt'); return {'jobs':0,'listings':0,'locked':True}
    total=0
    try:
        byid={p['id']:p for p in profiles}; jobs=build_jobs(profiles)
        for (source,regions,locations),pids in jobs.items():
            try: scraper=get_scraper(source)
            except KeyError: log.error('Unbekannte Quelle %s',source); continue
            try:
                params=SearchParams(nationwide='DE' in regions,region_codes=[] if 'DE' in regions else list(regions),locations=list(locations))
                listings=scraper.run(params); log.info('[%s] %d Inserate',source,len(listings)); total+=len(listings)
            except Exception: log.exception('[%s] Portal fehlgeschlagen',source); continue
            for item in listings:
                try:process_listing(item,byid,pids)
                except Exception:log.exception('Listing-Verarbeitung fehlgeschlagen: %s',item.url)
        return {'jobs':len(jobs),'listings':total}
    finally: db.release_scan_lock(lock)

def worker_loop():
    db.init_db()
    while True:
        started=time.time()
        try:run_once()
        except Exception:log.exception('Gesamtlauf fehlgeschlagen')
        time.sleep(max(0,POLL_INTERVAL_SECONDS-(time.time()-started)))

if __name__=='__main__': worker_loop()
