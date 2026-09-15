from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import uuid

import certifi
from pymongo import MongoClient, ASCENDING, DESCENDING, ReturnDocument
from pymongo.server_api import ServerApi
from pymongo.errors import DuplicateKeyError

MONGODB_URI = (os.getenv("MONGODB_URI") or "").strip()

def _database_name_from_uri(uri):
    configured = os.getenv("MONGO_DB_NAME")
    if configured:
        return configured
    try:
        path = urlparse(uri).path.strip("/") if uri else ""
        return path or "wohnung_saas"
    except Exception:
        return "wohnung_saas"

MONGO_DB_NAME = _database_name_from_uri(MONGODB_URI)
LOCK_KEY = "scan_lock"
# MongoDB scan lock is a short renewable lease. A long fixed stale timeout
# can leave an orphaned lock behind for 30 minutes after a deploy/crash.
LOCK_LEASE_SECONDS = max(60, int(os.getenv("SCAN_LOCK_LEASE_SECONDS", "300")))
LOCK_RENEW_INTERVAL_SECONDS = max(15, min(LOCK_LEASE_SECONDS // 3, int(os.getenv("SCAN_LOCK_RENEW_INTERVAL_SECONDS", "30"))))
LEGACY_LOCK_STALE_SECONDS = max(60, int(os.getenv("LEGACY_SCAN_LOCK_STALE_SECONDS", "120")))
# If an old/current lock was created but never renewed, treat it as orphaned
# after two renewal intervals. An active scan renews well before this point.
UNRENEWED_LOCK_STALE_SECONDS = max(90, LOCK_RENEW_INTERVAL_SECONDS * 3)
LOCK_INSTANCE_ID = (os.getenv("RENDER_INSTANCE_ID") or os.getenv("RENDER_SERVICE_ID") or str(uuid.uuid4())).strip()

_client = None


def _get_client():
    global _client
    if not MONGODB_URI:
        raise RuntimeError("MONGODB_URI fehlt")
    if _client is None:
        kwargs = {
            "serverSelectionTimeoutMS": int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "5000")),
            "connectTimeoutMS": int(os.getenv("MONGO_CONNECT_TIMEOUT_MS", "5000")),
            "socketTimeoutMS": int(os.getenv("MONGO_SOCKET_TIMEOUT_MS", "15000")),
            "retryWrites": True,
            "tls": True,
            "tlsCAFile": certifi.where(),
            "server_api": ServerApi("1"),
        }
        # TLS verification is deliberately kept enabled. Disabling certificate
        # verification would hide deployment/network problems instead of fixing them.
        if os.getenv("MONGO_TLS_INSECURE", "false").strip().lower() in {"1", "true", "yes", "on"}:
            kwargs["tlsAllowInvalidCertificates"] = True
            kwargs["tlsAllowInvalidHostnames"] = True
        _client = MongoClient(MONGODB_URI, **kwargs)
    return _client


def _db():
    return _get_client()[MONGO_DB_NAME]


def ping():
    _get_client().admin.command("ping")
    return True


def _now():
    return datetime.now(timezone.utc)


def _next_id(name):
    """Erzeugt fortlaufende Integer-IDs (Ersatz für SERIAL/BIGSERIAL),
    damit URL-Routen wie /profiles/<int:pid>/edit unverändert funktionieren."""
    doc = _db().counters.find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return doc["seq"]


def init_db():
    d = _db()
    d.profiles.create_index([("id", ASCENDING)], unique=True)
    d.profiles.create_index([("active", ASCENDING)])
    d.listings.create_index([("id", ASCENDING)], unique=True)
    d.listings.create_index([("source", ASCENDING), ("external_id", ASCENDING)], unique=True)
    d.listings.create_index([("last_seen", DESCENDING)])
    d.matches.create_index([("listing_id", ASCENDING), ("profile_id", ASCENDING)], unique=True)
    d.matches.create_index([("score", DESCENDING)])
    d.matches.create_index([("profile_id", ASCENDING), ("created_at", DESCENDING)])
    d.matches.create_index([("notified", ASCENDING)])
    d.scan_runs.create_index([("started_at", DESCENDING)])
    d.scan_state.create_index([("updated_at", DESCENDING)])
    d.source_health.create_index([("source", ASCENDING)], unique=True)
    d.scan_events.create_index([("run_id", ASCENDING), ("created_at", ASCENDING)])
    # Kein create_index auf "_id" nötig: MongoDB legt für _id immer schon
    # einen impliziten, eindeutigen Index an. unique=True darauf ist ungültig
    # (Fehler 197 InvalidIndexSpecificationOption) und lässt init_db() crashen.
    d.schema_meta.update_one({"_id": "schema"}, {"$set": {"schema_version": 3, "updated_at": _now()}}, upsert=True)


def cleanup_old_listings(days=60):
    """Löscht Inserate (und ihre Matches), die seit `days` Tagen in keinem
    Scan mehr gesehen wurden (last_seen)."""
    days = max(1, int(days))
    d = _db()
    cutoff = _now() - timedelta(days=days)
    old_ids = [row["id"] for row in d.listings.find({"last_seen": {"$lt": cutoff}}, {"id": 1})]
    if not old_ids:
        return 0
    d.matches.delete_many({"listing_id": {"$in": old_ids}})
    result = d.listings.delete_many({"id": {"$in": old_ids}})
    return result.deleted_count


def cleanup_scan_runs(days=30):
    days = max(0, int(days))
    cutoff = _now() - timedelta(days=days)
    _db().scan_runs.delete_many({"started_at": {"$lt": cutoff}})


def try_scan_lock():
    """Acquire the cross-process scan lock as a renewable MongoDB lease.

    Older deployments stored only ``acquired_at`` and used a 30-minute stale
    timeout. Such a lock could survive a crashed/deployed worker for a long
    time. New locks have ``lease_until`` and owner metadata; a scan renews the
    lease while it is running. Legacy lock documents without ``lease_until``
    are considered stale after a short migration window.
    """
    d = _db()
    now = _now()
    lease_until = now + timedelta(seconds=LOCK_LEASE_SECONDS)
    legacy_stale_before = now - timedelta(seconds=LEGACY_LOCK_STALE_SECONDS)
    unrenewed_stale_before = now - timedelta(seconds=UNRENEWED_LOCK_STALE_SECONDS)
    token = f"{LOCK_INSTANCE_ID}-{os.getpid()}-{uuid.uuid4().hex}"
    owner = {
        "token": token,
        "owner_pid": os.getpid(),
        "owner_instance": LOCK_INSTANCE_ID,
        "acquired_at": now,
        "lease_until": lease_until,
    }

    # Replace an expired lease atomically. For legacy locks without a lease,
    # only take over once their old acquired_at is past the migration timeout.
    doc = d.locks.find_one_and_update(
        {
            "_id": LOCK_KEY,
            "$or": [
                {"lease_until": {"$lt": now}},
                {
                    "lease_until": {"$exists": False},
                    "acquired_at": {"$lt": legacy_stale_before},
                },
                {
                    "lease_until": {"$exists": False},
                    "acquired_at": {"$exists": False},
                },
                {
                    "renewed_at": {"$exists": False},
                    "acquired_at": {"$lt": unrenewed_stale_before},
                },
                {
                    "renewed_at": None,
                    "acquired_at": {"$lt": unrenewed_stale_before},
                },
            ],
        },
        {"$set": owner},
        return_document=ReturnDocument.AFTER,
    )
    if doc and doc.get("token") == token:
        return token

    # No lock document exists yet. The insert is intentionally guarded
    # against a race with another process creating the lock at the same time.
    try:
        d.locks.insert_one({"_id": LOCK_KEY, **owner})
        return token
    except DuplicateKeyError:
        return None


def renew_scan_lock(conn):
    """Extend an active scan lease, but only for its owning token."""
    if not conn:
        return False
    now = _now()
    lease_until = now + timedelta(seconds=LOCK_LEASE_SECONDS)
    result = _db().locks.update_one(
        {"_id": LOCK_KEY, "token": conn},
        {"$set": {"lease_until": lease_until, "renewed_at": now}},
    )
    return result.matched_count == 1


def get_scan_lock():
    """Return diagnostic information about the current scan lock."""
    return _db().locks.find_one({"_id": LOCK_KEY}, {"_id": 0})


def release_scan_lock(conn):
    if not conn:
        return
    _db().locks.delete_one({"_id": LOCK_KEY, "token": conn})



def set_current_scan(run_id, *, pid=None, status="running", started_at=None,
                     jobs=None, mode="auto", progress=None, exit_code=None,
                     ended_at=None, error=None):
    """Persist the scan currently owned by the supervisor.

    This is deliberately a single MongoDB document so the dashboard can
    distinguish a running child process from the previous completed scan.
    """
    now = _now()
    doc = {
        "_id": "current",
        "run_id": str(run_id),
        "pid": pid,
        "status": status,
        "started_at": started_at or now,
        "updated_at": now,
        "jobs": jobs or [],
        "mode": mode,
        "progress": progress or {},
        "exit_code": exit_code,
        "ended_at": ended_at,
        "error": error,
    }
    _db().scan_state.replace_one({"_id": "current"}, doc, upsert=True)
    return doc


def update_current_scan(run_id, **fields):
    """Atomically update the current scan only when the run id still matches."""
    fields["updated_at"] = _now()
    result = _db().scan_state.update_one(
        {"_id": "current", "run_id": str(run_id)},
        {"$set": fields},
    )
    return result.matched_count == 1


def get_current_scan():
    doc = _db().scan_state.find_one({"_id": "current"}, {"_id": 0})
    return doc


def clear_current_scan(run_id, *, status="finished", exit_code=0, error=None):
    """Mark the current scan terminally; do not delete history."""
    now = _now()
    result = _db().scan_state.update_one(
        {"_id": "current", "run_id": str(run_id)},
        {"$set": {
            "status": status,
            "exit_code": exit_code,
            "ended_at": now,
            "updated_at": now,
            "error": error,
        }},
    )
    return result.matched_count == 1

def get_setup_stats():
    d = _db()
    active = d.profiles.count_documents({"active": True})
    with_sources = d.profiles.count_documents(
        {"active": True, "sources.0": {"$exists": True}}
    )
    runs = d.scan_runs.count_documents({})
    return {
        "active_profiles": active,
        "profiles_with_sources": with_sources,
        "scan_runs": runs,
    }


def _normalize_profile(p):
    if p is None:
        return None
    p.setdefault("sources", [])
    p.setdefault("regions", [])
    p.pop("_id", None)
    return p


def get_active_profiles():
    docs = list(_db().profiles.find({"active": True}).sort("id", ASCENDING))
    return [_normalize_profile(p) for p in docs]


def get_active_profiles_with_sources():
    docs = list(_db().profiles.find({"active": True}).sort("id", ASCENDING))
    return [_normalize_profile(p) for p in docs]


def get_profile(profile_id):
    p = _db().profiles.find_one({"id": profile_id})
    return _normalize_profile(p)


def add_profile(data):
    pid = _next_id("profiles")
    now = _now()
    doc = {
        "id": pid,
        "name": data.get("name"),
        "min_price": data.get("min_price"),
        "max_price": data.get("max_price"),
        "min_rooms": data.get("min_rooms"),
        "max_rooms": data.get("max_rooms"),
        "min_size": data.get("min_size"),
        "districts": data.get("districts"),
        "keywords_exclude": data.get("keywords_exclude"),
        "active": True,
        "sources": [],
        "regions": [],
        "created_at": now,
        "updated_at": now,
    }
    _db().profiles.insert_one(doc)
    return pid


def update_profile(pid, data):
    _db().profiles.update_one(
        {"id": pid},
        {"$set": {
            "name": data.get("name"),
            "min_price": data.get("min_price"),
            "max_price": data.get("max_price"),
            "min_rooms": data.get("min_rooms"),
            "max_rooms": data.get("max_rooms"),
            "min_size": data.get("min_size"),
            "districts": data.get("districts"),
            "keywords_exclude": data.get("keywords_exclude"),
            "active": data.get("active"),
            "updated_at": _now(),
        }},
    )


def set_profile_sources(pid, sources):
    _db().profiles.update_one(
        {"id": pid}, {"$set": {"sources": sorted(set(sources or []))}}
    )


def set_profile_regions(pid, regions):
    vals = sorted(set(regions or ["DE"]))
    _db().profiles.update_one({"id": pid}, {"$set": {"regions": vals}})


def delete_profile(pid):
    d = _db()
    d.profiles.delete_one({"id": pid})
    d.matches.delete_many({"profile_id": pid})


def _listing_changed(existing, data):
    fields = ("title", "description", "price", "price_total", "rooms", "size", "location", "city",
              "postal_code", "url", "published_at", "raw")
    return any(existing.get(f) != data.get(f) for f in fields)


def _data_completeness(data):
    fields=("url","title","price_total","price","rooms","size","city","postal_code","address","published_at")
    return round(100 * sum(1 for f in fields if data.get(f) not in (None, "")) / len(fields))


def upsert_listing(item):
    d = _db(); now = _now(); data = dict(item.__dict__)
    data.setdefault("raw", {})
    # Normalize aliases and ensure all absent values remain null rather than fabricated.
    data["price"] = data.get("cold_rent") if data.get("cold_rent") is not None else data.get("price")
    data["price_total"] = data.get("warm_rent") if data.get("warm_rent") is not None else data.get("price_total")
    key={"source": data.get("source"), "external_id": data.get("external_id")}
    existing=d.listings.find_one(key)
    if existing:
        changed=_listing_changed(existing,data)
        update_fields={
            "title":data.get("title"),"description":data.get("description"),"price":data.get("price"),"price_total":data.get("price_total"),
            "cold_rent":data.get("cold_rent"),"warm_rent":data.get("warm_rent"),"utilities":data.get("utilities"),"heating_costs":data.get("heating_costs"),
            "total_rent":data.get("total_rent"),"rent_type":data.get("rent_type"),"rent_confidence":data.get("rent_confidence"),
            "rooms":data.get("rooms"),"size":data.get("size"),"location":data.get("address"),"city":data.get("city"),"district":data.get("district"),
            "neighborhood":data.get("neighborhood"),"postal_code":data.get("postal_code"),"region_code":data.get("region_code"),"street":data.get("street"),
            "floor":data.get("floor"),"total_floors":data.get("total_floors"),"balcony":data.get("balcony"),"terrace":data.get("terrace"),"garden":data.get("garden"),
            "elevator":data.get("elevator"),"fitted_kitchen":data.get("fitted_kitchen"),"furnished":data.get("furnished"),"wg_possible":data.get("wg_possible"),
            "temporary":data.get("temporary"),"swap":data.get("swap"),"wbs_required":data.get("wbs_required"),"commission":data.get("commission"),
            "commission_free":data.get("commission_free"),"parking":data.get("parking"),"cellar":data.get("cellar"),"pets_allowed":data.get("pets_allowed"),
            "smoking_allowed":data.get("smoking_allowed"),"available_from":data.get("available_from"),"published_at":existing.get("published_at") or data.get("published_at"),
            "provider":data.get("provider"),"contact_name":data.get("contact_name"),"contact_phone":data.get("contact_phone"),"images_count":data.get("images_count"),
            "url":data.get("url"),"raw":data.get("raw") or {},"last_seen":now,"last_status":"UPDATED" if changed else "UNCHANGED",
            "status":"UPDATED" if changed else "ACTIVE","last_changed":now if changed else existing.get("last_changed"),
            "missing_since":None,"data_completeness_score":_data_completeness(data),
        }
        d.listings.update_one({"id":existing["id"]},{"$set":update_fields})
        return existing["id"], False
    lid=_next_id("listings")
    doc={"id":lid,"source":data.get("source"),"external_id":data.get("external_id"),"title":data.get("title"),"description":data.get("description"),
         "price":data.get("price"),"price_total":data.get("price_total"),"cold_rent":data.get("cold_rent"),"warm_rent":data.get("warm_rent"),
         "utilities":data.get("utilities"),"heating_costs":data.get("heating_costs"),"total_rent":data.get("total_rent"),"rent_type":data.get("rent_type"),
         "rent_confidence":data.get("rent_confidence"),"rooms":data.get("rooms"),"size":data.get("size"),"location":data.get("address"),"city":data.get("city"),
         "district":data.get("district"),"neighborhood":data.get("neighborhood"),"postal_code":data.get("postal_code"),"region_code":data.get("region_code"),
         "street":data.get("street"),"floor":data.get("floor"),"total_floors":data.get("total_floors"),"balcony":data.get("balcony"),"terrace":data.get("terrace"),
         "garden":data.get("garden"),"elevator":data.get("elevator"),"fitted_kitchen":data.get("fitted_kitchen"),"furnished":data.get("furnished"),"wg_possible":data.get("wg_possible"),
         "temporary":data.get("temporary"),"swap":data.get("swap"),"wbs_required":data.get("wbs_required"),"commission":data.get("commission"),"commission_free":data.get("commission_free"),
         "parking":data.get("parking"),"cellar":data.get("cellar"),"pets_allowed":data.get("pets_allowed"),"smoking_allowed":data.get("smoking_allowed"),
         "available_from":data.get("available_from"),"published_at":data.get("published_at"),"first_seen":now,"last_seen":now,"last_changed":now,"missing_since":None,
         "status":"NEW","last_status":"NEW","provider":data.get("provider"),"contact_name":data.get("contact_name"),"contact_phone":data.get("contact_phone"),"images_count":data.get("images_count"),
         "data_completeness_score":_data_completeness(data),"raw":data.get("raw") or {}}
    try:d.listings.insert_one(doc)
    except DuplicateKeyError:
        existing=d.listings.find_one(key); return existing["id"],False
    return lid,True


def get_listing(listing_id):
    return _db().listings.find_one({"id":listing_id},{"_id":0})


def mark_listings_missing(source: str, seen_external_ids: set[str], scan_started_at=None):
    """Mark source listings missing only after a source completed successfully.
    This prevents a blocked/broken portal from making every listing disappear."""
    d=_db(); now=_now(); query={"source":source,"status":{"$in":["NEW","ACTIVE","UPDATED","UNCHANGED"]}}
    if seen_external_ids: query["external_id"]={"$nin":list(seen_external_ids)}
    result=d.listings.update_many(query,{"$set":{"status":"MISSING","missing_since":now,"last_status":"MISSING"}})
    return result.modified_count


def update_source_health(source, *, status, result_count=0, error=None, duration_seconds=None, parser_ok=True, blocked=False):
    d=_db(); now=_now(); previous=d.source_health.find_one({"source":source}) or {}
    failures=int(previous.get("consecutive_failures",0)); empties=int(previous.get("consecutive_empty_results",0))
    if status in {"failed","blocked","unavailable","timeout"}: failures+=1
    else: failures=0
    if status=="empty": empties+=1
    else: empties=0
    if status in {"finished","empty"}: last_success=now
    else: last_success=previous.get("last_success")
    health="QUARANTINED" if failures>=10 else "DEGRADED" if failures>=5 or blocked else "HEALTHY"
    d.source_health.update_one({"source":source},{"$set":{"source":source,"status":health,"last_status":status,"last_attempt":now,"last_success":last_success,"last_error":error,"last_result_count":result_count,"consecutive_failures":failures,"consecutive_empty_results":empties,"blocked_count":int(previous.get("blocked_count",0))+(1 if blocked else 0),"average_duration":duration_seconds if duration_seconds is not None else previous.get("average_duration"),"parser_health":parser_ok,"updated_at":now,"source_quality_score":max(0,min(100,100-failures*10-(20 if blocked else 0)-(10 if empties>=3 else 0))),"circuit_state":"OPEN" if failures>=10 else "HALF_OPEN" if failures>=5 else "CLOSED"}},upsert=True)
    return health


def get_source_health():
    return list(_db().source_health.find({}, {"_id":0}).sort("source", ASCENDING))

def save_match(listing_id, profile_id, score, components, reasons):
    price_score, rooms_score, size_score, location_score = components
    now = _now()
    d = _db()
    previous = d.matches.find_one({"listing_id": listing_id, "profile_id": profile_id}) or {}
    previous_score = previous.get("score")
    update_fields = {
        "score": score,
        "price_score": price_score,
        "rooms_score": rooms_score,
        "size_score": size_score,
        "location_score": location_score,
        "reasons": reasons,
        "updated_at": now,
    }
    # One atomic operation avoids the find-then-insert race when two workers
    # process the same listing/profile concurrently. Existing notification
    # flags are preserved.
    doc = d.matches.find_one_and_update(
        {"listing_id": listing_id, "profile_id": profile_id},
        {
            "$set": update_fields,
            "$setOnInsert": {
                "listing_id": listing_id,
                "profile_id": profile_id,
                "notified": False,
                "telegram_notified": False,
                "email_notified": False,
                "created_at": now,
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return {
        "notified": doc.get("notified", False),
        "telegram_notified": doc.get("telegram_notified", False),
        "email_notified": doc.get("email_notified", False),
        "previous_score": previous_score,
        "score_improved": previous_score is not None and score >= previous_score + 10,
    }


def reset_match_notifications(listing_id, profile_id):
    _db().matches.update_one({"listing_id":listing_id,"profile_id":profile_id},{"$set":{"telegram_notified":False,"email_notified":False,"notified":False,"updated_at":_now()}})


def mark_telegram_notified(listing_id, profile_id):
    _db().matches.update_one(
        {"listing_id": listing_id, "profile_id": profile_id},
        {"$set": {"telegram_notified": True, "notified": True, "updated_at": _now()}},
    )


def mark_email_notified(listing_id, profile_id):
    _db().matches.update_one(
        {"listing_id": listing_id, "profile_id": profile_id},
        {"$set": {"email_notified": True, "notified": True, "updated_at": _now()}},
    )


def mark_notified(listing_id, profile_id):
    """Backward-compatible helper: mark the overall match as notified."""
    _db().matches.update_one(
        {"listing_id": listing_id, "profile_id": profile_id},
        {"$set": {"notified": True, "updated_at": _now()}},
    )


def save_scan_run(summary, duration_seconds=None, started_at=None):
    sid = _next_id("scan_runs")
    _db().scan_runs.insert_one({
        "id": sid,
        "started_at": started_at or _now(),
        "duration_seconds": duration_seconds,
        "summary": summary,
    })


def get_last_scan_run():
    doc = _db().scan_runs.find_one(sort=[("started_at", DESCENDING)])
    if doc:
        doc.pop("_id", None)
    return doc

def get_recent_scan_runs(limit=10):
    limit=max(1,int(limit))
    docs=list(_db().scan_runs.find({}, {"_id":0}).sort("started_at", DESCENDING).limit(limit))
    return docs


def record_worker_heartbeat(duration_seconds=None, pid=None, poll_interval_seconds=None):
    """Vom Worker nach JEDEM Zyklus aufzurufen (auch bei Exceptions, auch ohne
    aktive Profile) – VOR dem sleep. Einzige Zeile (id=1), daher Upsert."""
    _db().worker_heartbeat.update_one(
        {"_id": 1},
        {"$set": {
            "last_seen_at": _now(),
            "last_cycle_duration_seconds": duration_seconds,
            "pid": pid,
            "poll_interval_seconds": poll_interval_seconds,
        }},
        upsert=True,
    )


def get_worker_heartbeat():
    doc = _db().worker_heartbeat.find_one({"_id": 1})
    if doc:
        doc.pop("_id", None)
    return doc


DASHBOARD_LIMIT = max(1, int(os.getenv("DASHBOARD_LIMIT", "300")))


def get_dashboard_rows(min_score=0, profile_id=None, limit=None):
    limit = DASHBOARD_LIMIT if limit is None else max(1, int(limit))
    d = _db()
    match_filter = {"score": {"$gte": min_score}}
    if profile_id:
        match_filter["profile_id"] = profile_id

    pipeline = [
        {"$match": match_filter},
        {"$sort": {"score": DESCENDING, "created_at": DESCENDING}},
        {"$limit": limit},
        {"$lookup": {
            "from": "listings", "localField": "listing_id",
            "foreignField": "id", "as": "listing",
        }},
        {"$unwind": "$listing"},
        {"$lookup": {
            "from": "profiles", "localField": "profile_id",
            "foreignField": "id", "as": "profile",
        }},
        {"$unwind": "$profile"},
    ]
    rows = []
    for doc in d.matches.aggregate(pipeline):
        listing = doc["listing"]
        profile = doc["profile"]
        rows.append({
            "listing_id": doc["listing_id"],
            "profile_id": doc["profile_id"],
            "score": doc.get("score"),
            "price_score": doc.get("price_score"),
            "rooms_score": doc.get("rooms_score"),
            "size_score": doc.get("size_score"),
            "location_score": doc.get("location_score"),
            "reasons": doc.get("reasons"),
            "notified": doc.get("notified"),
            "telegram_notified": doc.get("telegram_notified"),
            "email_notified": doc.get("email_notified"),
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
            "title": listing.get("title"),
            "price": listing.get("price"),
            "price_total": listing.get("price_total"),
            "rooms": listing.get("rooms"),
            "size": listing.get("size"),
            "location": listing.get("location"),
            "url": listing.get("url"),
            "source": listing.get("source"),
            "first_seen": listing.get("first_seen"),
            "last_seen": listing.get("last_seen"),
            "last_changed": listing.get("last_changed"),
            "status": listing.get("status"),
            "data_completeness_score": listing.get("data_completeness_score"),
            "warm_rent": listing.get("warm_rent"),
            "cold_rent": listing.get("cold_rent"),
            "profile_name": profile.get("name"),
        })
    return rows


def source_circuit_state(source):
    doc=_db().source_health.find_one({"source":source}) or {}
    failures=int(doc.get("consecutive_failures",0)); state=doc.get("circuit_state") or ("OPEN" if failures>=10 else "HALF_OPEN" if failures>=5 else "CLOSED")
    if state == "OPEN":
        opened=doc.get("circuit_updated_at")
        if opened and (_now()-opened).total_seconds() >= 1800:
            _db().source_health.update_one({"source":source},{"$set":{"circuit_state":"HALF_OPEN"}})
            return "HALF_OPEN"
    return state

def set_source_circuit(source, state):
    _db().source_health.update_one({"source":source},{"$set":{"circuit_state":state,"circuit_updated_at":_now()}},upsert=True)
