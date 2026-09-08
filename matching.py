from __future__ import annotations
import re

WEIGHTS=(.35,.20,.25,.20)
TOLERANCE=.05

def _tokens(value): return [x.strip().casefold() for x in re.split(r'[,;\n]+', value or '') if x.strip()]

def score_listing(listing, profile):
    text=' '.join(str(listing.get(k) or '') for k in ('title','description','location','address')).casefold()
    excludes=_tokens(profile.get('keywords_exclude'))
    hit=next((x for x in excludes if x in text),None)
    if hit: return None
    price=listing.get('price') or listing.get('price_total')
    max_price=float(profile.get('max_price') or 0)
    if max_price and price is not None and float(price)>max_price*(1+TOLERANCE): return None
    min_size=float(profile.get('min_size') or 0)
    size=listing.get('size')
    if min_size and size is not None and float(size)<min_size: return None
    min_rooms=float(profile.get('min_rooms') or 0); max_rooms=profile.get('max_rooms'); rooms=listing.get('rooms')
    if rooms is not None and min_rooms and float(rooms)<min_rooms: return None
    if rooms is not None and max_rooms is not None and float(rooms)>float(max_rooms): return None

    # Price: full score at/below budget, linearly reduced through the 5% tolerance band.
    if max_price<=0 or price is None: price_score=70
    elif float(price)<=max_price: price_score=100
    else: price_score=max(0,round(100*(1-(float(price)-max_price)/(max_price*TOLERANCE))))

    if rooms is None or min_rooms<=0: rooms_score=70
    elif float(rooms)>=min_rooms:
        if max_rooms is not None and float(rooms)>float(max_rooms): rooms_score=0
        else: rooms_score=100
    else: rooms_score=max(0,round(100*float(rooms)/min_rooms))

    if size is None or min_size<=0: size_score=70
    else: size_score=min(100,round(100*float(size)/min_size))

    districts=_tokens(profile.get('districts'))
    location_score=70 if not districts else (100 if any(d in text for d in districts) else 35)
    score=round(price_score*.35+rooms_score*.20+size_score*.25+location_score*.20)
    reasons=[]
    if price is not None: reasons.append(f"Preis {price:.0f} €")
    if rooms is not None: reasons.append(f"{rooms:g} Zimmer")
    if size is not None: reasons.append(f"{size:g} m²")
    if districts: reasons.append("Lage passend" if location_score==100 else "Lage nicht eindeutig")
    return score,(round(price_score*.35),round(rooms_score*.20),round(size_score*.25),round(location_score*.20)),reasons
