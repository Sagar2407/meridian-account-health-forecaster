"""
generators.py
=============
All generation logic for the Meridian Account-Health dataset.

Causal chain (this ordering is deliberate):
    accounts  ->  weekly usage (archetype-driven trajectories)
              ->  external events (adverse/favorable, some tied to usage cliffs)
              ->  support tickets (volume/tone conditioned on health & events)
              ->  CSM notes / QBRs (narrative conditioned on everything above)
              ->  observable features  ->  renewal outcome (+ noise) + drivers

The renewal outcome is a function of OBSERVABLE features only (plus irreducible
noise), so a model that sees the features has genuine, learnable signal. The
latent 'health_archetype' is recorded for analysis but must not be used as a
feature.
"""

import numpy as np
import pandas as pd
from datetime import date, timedelta

import config as C
import text_banks as T

# --------------------------------------------------------------------------- #
# RNG + small helpers
# --------------------------------------------------------------------------- #
def make_rng():
    return np.random.default_rng(C.RANDOM_SEED)

def pick(rng, seq):
    return seq[int(rng.integers(0, len(seq)))]

def pick_p(rng, seq, probs):
    probs = np.array(probs, dtype=float)
    probs = probs / probs.sum()
    return seq[int(rng.choice(len(seq), p=probs))]

def clip(x, lo, hi):
    return max(lo, min(hi, x))

BAND_FOR_ARCHETYPE = {
    "expanding": "thriving",
    "stable_healthy": "steady",
    "seasonal_healthy": "steady",
    "slow_decline": "slipping",
    "sharp_drop": "at_risk",
    "onboarding_stall": "stalled",
    "recovered": "recovering",
}

# Window of weekly dates (list of date objects), oldest -> newest.
WEEK_STARTS = [C.AS_OF_DATE - timedelta(weeks=k) for k in range(C.WINDOW_WEEKS - 1, -1, -1)]
WINDOW_START = WEEK_STARTS[0]

# Event headline templates (synthetic; stand in for live news/market signals).
EVENT_HEADLINES = {
    "Leadership change (CxO)":       "{company} announced a change in {role}",
    "Layoffs / restructuring":       "{company} announced layoffs affecting an estimated {pct}% of staff",
    "Earnings miss":                 "{company} missed quarterly revenue expectations",
    "Acquisition (as target)":       "{company} agreed to be acquired",
    "Cost-cutting initiative":       "{company} launched a company-wide cost-reduction program",
    "Regulatory / compliance issue": "{company} disclosed a regulatory inquiry",
    "Earnings beat":                 "{company} beat quarterly earnings estimates",
    "Funding round / capital raise": "{company} raised a new round of capital",
    "Acquisition (as acquirer)":     "{company} acquired a smaller competitor",
    "New product / market launch":   "{company} launched into a new market segment",
    "Executive hire (digital/CX)":   "{company} hired a new {role} to lead digital",
    "Partnership announcement":      "{company} announced a strategic partnership",
    "Office relocation":             "{company} relocated its headquarters",
}
CXO_ROLES = ["CEO", "CMO", "CIO", "CDO", "CFO", "Chief Digital Officer"]


# =========================================================================== #
# 1. ACCOUNTS
# =========================================================================== #
def _make_company_names(rng, n):
    names, seen = [], set()
    tries = 0
    while len(names) < n and tries < n * 50:
        tries += 1
        nm = f"{pick(rng, C.COMPANY_PREFIXES)}{pick(rng, C.COMPANY_ROOTS)} {pick(rng, C.COMPANY_SUFFIXES)}".strip()
        if nm not in seen:
            seen.add(nm)
            names.append(nm)
    # pad if needed
    i = 0
    while len(names) < n:
        names.append(f"{pick(rng, C.COMPANY_PREFIXES)}{pick(rng, C.COMPANY_ROOTS)} {i}")
        i += 1
    return names

def _person(rng):
    return f"{pick(rng, C.FIRST_NAMES)} {pick(rng, C.LAST_NAMES)}"

def generate_accounts(rng):
    names = _make_company_names(rng, C.N_ACCOUNTS)
    seg_names = C.SEGMENT_NAMES
    seg_w = [C.SEGMENTS[s]["weight"] for s in seg_names]
    arch_names = C.ARCHETYPE_NAMES
    arch_w = [C.ARCHETYPES[a]["weight"] for a in arch_names]
    reg_names = list(C.REGION_WEIGHTS.keys())
    reg_w = [C.REGION_WEIGHTS[r] for r in reg_names]

    rows = []
    for i in range(C.N_ACCOUNTS):
        aid = f"ACC-{1000 + i}"
        segment = pick_p(rng, seg_names, seg_w)
        seg = C.SEGMENTS[segment]
        archetype = pick_p(rng, arch_names, arch_w)
        arch = C.ARCHETYPES[archetype]
        band = BAND_FOR_ARCHETYPE[archetype]

        industry = pick(rng, C.INDUSTRY_NAMES)
        region = pick_p(rng, reg_names, reg_w)
        country = pick(rng, C.REGIONS[region])

        seats = int(rng.integers(seg["seat_range"][0], seg["seat_range"][1] + 1))
        acv = float(rng.integers(seg["acv_range"][0] // 1000, seg["acv_range"][1] // 1000 + 1) * 1000)
        n_products = int(rng.integers(seg["product_count_range"][0], seg["product_count_range"][1] + 1))

        # product attach weighted
        pw = np.array([C.PRODUCTS[p]["attach_weight"] for p in C.PRODUCT_NAMES], dtype=float)
        pw = pw / pw.sum()
        products = list(rng.choice(C.PRODUCT_NAMES, size=n_products, replace=False, p=pw))
        primary_product = products[0]

        # contract start (tenure) & upcoming renewal near "now"
        cs_span = (date(2025, 10, 1) - date(2023, 1, 1)).days
        contract_start = date(2023, 1, 1) + timedelta(days=int(rng.integers(0, cs_span)))
        term = pick_p(rng, list(seg["term_weights"].keys()), list(seg["term_weights"].values()))
        rn_span = (date(2026, 12, 15) - date(2025, 11, 1)).days
        renewal_date = date(2025, 11, 1) + timedelta(days=int(rng.integers(0, rn_span)))
        forecast_as_of = renewal_date - timedelta(days=C.FORECAST_HORIZON_DAYS)

        # onboarding completion
        if band == "stalled":
            onboarding_completed = rng.random() > 0.85
        elif band in ("thriving",):
            onboarding_completed = True
        else:
            onboarding_completed = rng.random() > 0.08

        # sponsor status
        changed = rng.random() < arch["sponsor_change_p"]
        if changed:
            if band in ("at_risk", "slipping", "stalled"):
                sponsor_status = "lost" if rng.random() < 0.6 else "new"
            else:
                sponsor_status = "new" if rng.random() < 0.8 else "lost"
        else:
            sponsor_status = "strong" if band == "thriving" else "stable"

        adv_lo, adv_hi = arch["advanced_adoption"]
        advanced_adoption = float(rng.uniform(adv_lo, adv_hi))

        rows.append({
            "account_id": aid,
            "account_name": names[i],
            "segment": segment,
            "industry": industry,
            "region": region,
            "country": country,
            "employees": int(seats * rng.integers(20, 60)),
            "licensed_seats": seats,
            "acv_usd": acv,
            "contract_term_months": term,
            "contract_start_date": contract_start.isoformat(),
            "renewal_date": renewal_date.isoformat(),
            "forecast_as_of_date": forecast_as_of.isoformat(),
            "products_owned": ";".join(products),
            "num_products": n_products,
            "primary_product": primary_product,
            "csm_name": _person(rng),
            "exec_sponsor_name": _person(rng),
            "sponsor_status": sponsor_status,
            "onboarding_completed": bool(onboarding_completed),
            "advanced_adoption_target": round(advanced_adoption, 3),
            # latent ground truth (NOT a feature)
            "health_archetype": archetype,
            "_band": band,
        })
    return pd.DataFrame(rows)


# =========================================================================== #
# 2. USAGE  (weekly engagement trajectories per archetype)
# =========================================================================== #
def _trajectory(rng, arch, L, is_new):
    """Return engagement level array (len L, ~0..1.1) for the active window."""
    s, e = arch["start_level"], arch["end_level"]
    shape = arch["shape"]
    vol = arch["volatility"]
    t = np.linspace(0, 1, L)

    if shape == "growth":
        base = s + (e - s) * (t ** 0.9)
    elif shape == "flat":
        base = np.full(L, (s + e) / 2.0) + (e - s) * (t - 0.5)
    elif shape == "decay":
        base = s + (e - s) * (t ** 1.25)
    elif shape == "cliff":
        drop = float(rng.uniform(0.55, 0.8))
        width = max(2, int(L * 0.05))
        base = np.where(t < drop, s, e)
        di = int(drop * L)
        for k in range(width):
            if di + k < L:
                frac = k / width
                base[di + k] = s + (e - s) * frac
        base[min(di + width, L - 1):] = e
    elif shape == "stall":
        ramp = max(3, int(L * 0.06))
        base = np.full(L, e)
        for k in range(min(ramp, L)):
            base[k] = 0.06 + (s - 0.06) * (k / max(1, ramp))
        base[ramp:] = np.linspace(s, e, max(1, L - ramp))
    elif shape == "vshape":
        dip_center = float(rng.uniform(0.4, 0.55))
        dip_min = float(rng.uniform(0.30, 0.38))
        di = int(dip_center * L)
        down = np.linspace(s, dip_min, max(1, di))
        up = np.linspace(dip_min, e, max(1, L - di))
        base = np.concatenate([down, up])[:L]
    else:
        base = np.full(L, (s + e) / 2.0)

    # onboarding ramp for genuinely new accounts (blend first weeks up from ~0.08)
    if is_new and shape not in ("stall",):
        ramp = max(4, int(L * 0.07))
        for k in range(min(ramp, L)):
            frac = k / max(1, ramp)
            base[k] = 0.08 + (base[k] - 0.08) * frac

    noise = rng.normal(0, vol, L)
    lvl = np.clip(base + noise, 0.02, 1.15)
    return lvl

def generate_usage(rng, accounts):
    """Return (usage_df, adoption_series_dict, drop_week_dict)."""
    rows = []
    adoption_series = {}     # account_id -> np.array aligned to WEEK_STARTS (nan before active)
    drop_week = {}           # account_id -> date of usage cliff (sharp_drop) or None

    for _, a in accounts.iterrows():
        aid = a["account_id"]
        arch = C.ARCHETYPES[a["health_archetype"]]
        seats = int(a["licensed_seats"])
        products = a["products_owned"].split(";")
        seasonal_mult_by_month = C.INDUSTRIES[a["industry"]]
        seasonal_gain = arch.get("seasonal_gain", 1.0)

        cs = date.fromisoformat(a["contract_start_date"])
        # active start index in window
        active_start = 0
        is_new = False
        if cs > WINDOW_START:
            active_start = next((i for i, w in enumerate(WEEK_STARTS) if w >= cs), 0)
            is_new = True
        L = C.WINDOW_WEEKS - active_start
        lvl = _trajectory(rng, arch, L, is_new)

        # per-account weekly adoption series (avg across products), aligned to full window
        series = np.full(C.WINDOW_WEEKS, np.nan)

        # per-product static offset
        prod_offset = {p: float(rng.normal(1.0, 0.10)) for p in products}

        # detect cliff week for events linkage
        if arch["shape"] == "cliff":
            # approximate: first big week-over-week drop
            d = np.diff(lvl)
            idx = int(np.argmin(d))
            drop_week[aid] = WEEK_STARTS[active_start + idx]
        else:
            drop_week[aid] = None

        for wi in range(L):
            gi = active_start + wi
            wk = WEEK_STARTS[gi]
            month = wk.month
            seas = 1.0 + (seasonal_mult_by_month[month - 1] - 1.0) * seasonal_gain
            base_lvl = clip(lvl[wi] * seas, 0.02, 1.3)
            week_prod_levels = []
            for p in products:
                pl = clip(base_lvl * prod_offset[p], 0.01, 1.4)
                week_prod_levels.append(pl)
                pcfg = C.PRODUCTS[p]
                active_users = int(round(min(seats, seats * pl * float(rng.uniform(0.6, 0.95)))))
                active_users = max(0, active_users)
                sessions = int(round(active_users * pcfg["sessions_per_seat"] * (0.5 + 0.6 * pl)))
                feature_events = int(round(sessions * pcfg["feature_events_per_session"] * (0.5 + 0.7 * pl)))
                api_calls = int(round(active_users * pcfg["api_calls_per_seat"] * (0.4 + 0.7 * pl)))
                storage_gb = round(seats * pcfg["storage_gb_per_seat"] * (0.5 + 0.6 * pl) * prod_offset[p], 2)
                adv_pct = round(clip(100 * a["advanced_adoption_target"] * (0.45 + 0.65 * pl), 0, 100), 1)
                rows.append({
                    "account_id": aid,
                    "week_start": wk.isoformat(),
                    "product": p,
                    "active_users": active_users,
                    "sessions": sessions,
                    "feature_events": feature_events,
                    "api_calls": api_calls,
                    "storage_gb": storage_gb,
                    "advanced_feature_adoption_pct": adv_pct,
                })
            series[gi] = round(100 * float(np.mean(week_prod_levels)), 1)
        adoption_series[aid] = series

    usage_df = pd.DataFrame(rows)
    return usage_df, adoption_series, drop_week


# =========================================================================== #
# 3. EXTERNAL EVENTS  (synthetic stand-ins for live news/market signals)
# =========================================================================== #
def generate_external_events(rng, accounts, drop_week):
    rows = []
    etypes = list(C.EXTERNAL_EVENT_TYPES.keys())
    for _, a in accounts.iterrows():
        aid = a["account_id"]
        band = a["_band"]
        company = a["account_name"]
        # base number of events over window
        n_events = int(rng.poisson(2.2))
        # tilt polarity by band
        if band in ("at_risk", "slipping", "stalled"):
            headwind_p = 0.62
        elif band in ("thriving",):
            headwind_p = 0.20
        else:
            headwind_p = 0.38

        events_for_acc = []

        # tie an adverse event to the usage cliff for sharp_drop accounts
        if drop_week.get(aid) is not None and rng.random() < 0.8:
            ev_type = pick_p(rng,
                             ["Leadership change (CxO)", "Layoffs / restructuring",
                              "Acquisition (as target)", "Cost-cutting initiative"],
                             [0.3, 0.3, 0.2, 0.2])
            dw = drop_week[aid]
            ev_date = dw - timedelta(days=int(rng.integers(0, 35)))  # shortly before the drop
            events_for_acc.append((ev_type, ev_date))

        for _ in range(n_events):
            headwind = rng.random() < headwind_p
            pool = [e for e in etypes if (C.EXTERNAL_EVENT_TYPES[e] < 0) == headwind] or etypes
            ev_type = pick(rng, pool)
            off = int(rng.integers(0, C.WINDOW_WEEKS * 7))
            ev_date = WINDOW_START + timedelta(days=off)
            events_for_acc.append((ev_type, ev_date))

        for ev_type, ev_date in events_for_acc:
            polarity = C.EXTERNAL_EVENT_TYPES[ev_type]
            tmpl = EVENT_HEADLINES[ev_type]
            headline = tmpl.format(company=company,
                                   role=pick(rng, CXO_ROLES),
                                   pct=int(rng.integers(4, 15)))
            rows.append({
                "account_id": aid,
                "event_date": ev_date.isoformat(),
                "event_type": ev_type,
                "polarity": polarity,      # +1 tailwind / -1 headwind / 0 neutral
                "source": pick(rng, ["News wire", "Company press release", "Market data", "Trade publication"]),
                "headline": headline,
            })
    df = pd.DataFrame(rows).sort_values(["account_id", "event_date"]).reset_index(drop=True)
    return df


# =========================================================================== #
# 4. SUPPORT TICKETS
# =========================================================================== #
TONE_DIST_BY_BAND = {
    "thriving":   {"positive": .50, "neutral": .40, "frustrated": .05, "urgent": .05},
    "steady":     {"positive": .30, "neutral": .55, "frustrated": .10, "urgent": .05},
    "slipping":   {"positive": .12, "neutral": .50, "frustrated": .28, "urgent": .10},
    "at_risk":    {"positive": .05, "neutral": .35, "frustrated": .38, "urgent": .22},
    "stalled":    {"positive": .05, "neutral": .50, "frustrated": .30, "urgent": .15},
    "recovering": {"positive": .25, "neutral": .50, "frustrated": .18, "urgent": .07},
}
CATEGORY_DIST_BY_BAND = {
    "thriving":   {"How-to / Usage": .22, "Feature Request": .30, "Integration / API": .18,
                   "Onboarding / Enablement": .08, "Bug / Defect": .10, "Billing / Licensing": .07,
                   "Performance / Outage": .04, "Escalation": .01},
    "steady":     {"How-to / Usage": .28, "Feature Request": .18, "Integration / API": .16,
                   "Onboarding / Enablement": .06, "Bug / Defect": .16, "Billing / Licensing": .08,
                   "Performance / Outage": .06, "Escalation": .02},
    "slipping":   {"How-to / Usage": .22, "Feature Request": .10, "Integration / API": .14,
                   "Onboarding / Enablement": .06, "Bug / Defect": .22, "Billing / Licensing": .08,
                   "Performance / Outage": .12, "Escalation": .06},
    "at_risk":    {"How-to / Usage": .12, "Feature Request": .05, "Integration / API": .12,
                   "Onboarding / Enablement": .05, "Bug / Defect": .24, "Billing / Licensing": .07,
                   "Performance / Outage": .17, "Escalation": .18},
    "stalled":    {"How-to / Usage": .20, "Feature Request": .05, "Integration / API": .12,
                   "Onboarding / Enablement": .28, "Bug / Defect": .16, "Billing / Licensing": .07,
                   "Performance / Outage": .06, "Escalation": .06},
    "recovering": {"How-to / Usage": .22, "Feature Request": .12, "Integration / API": .16,
                   "Onboarding / Enablement": .08, "Bug / Defect": .18, "Billing / Licensing": .07,
                   "Performance / Outage": .09, "Escalation": .08},
}
TONE_SENTIMENT = {"positive": (0.60, 0.15), "neutral": (0.00, 0.12),
                  "frustrated": (-0.50, 0.15), "urgent": (-0.30, 0.18)}
TONE_CSAT = {"positive": [5, 5, 4], "neutral": [4, 3, 4], "frustrated": [2, 1, 2], "urgent": [3, 2, 2]}
PRIORITY_BY_CATEGORY = {
    "Escalation": ["P1", "P1", "P2"],
    "Performance / Outage": ["P1", "P2", "P2"],
    "Bug / Defect": ["P2", "P3", "P3"],
    "Integration / API": ["P2", "P3", "P3"],
    "Billing / Licensing": ["P3", "P4"],
    "How-to / Usage": ["P3", "P4", "P4"],
    "Feature Request": ["P4", "P4"],
    "Onboarding / Enablement": ["P3", "P3", "P4"],
}
RES_HOURS_BY_PRIORITY = {"P1": (2, 12), "P2": (6, 36), "P3": (12, 72), "P4": (24, 160)}

def _active_range(accounts_row):
    cs = date.fromisoformat(accounts_row["contract_start_date"])
    start = max(cs, WINDOW_START)
    return start, C.AS_OF_DATE

def generate_tickets(rng, accounts, drop_week):
    rows = []
    tk = 0
    for _, a in accounts.iterrows():
        aid = a["account_id"]
        band = a["_band"]
        arch = C.ARCHETYPES[a["health_archetype"]]
        seats = int(a["licensed_seats"])
        products = a["products_owned"].split(";")
        company = a["account_name"]
        csm = a["csm_name"]
        industry = a["industry"]

        start, end = _active_range(a)
        active_weeks = max(1, (end - start).days // 7)
        seat_factor = clip(seats / 60.0, 0.4, 3.0)
        exp_tickets = active_weeks * 0.15 * arch["ticket_rate"] * seat_factor
        n_tickets = int(rng.poisson(max(0.5, exp_tickets)))

        tone_names = list(TONE_DIST_BY_BAND[band].keys())
        tone_probs = list(TONE_DIST_BY_BAND[band].values())
        cat_names = list(CATEGORY_DIST_BY_BAND[band].keys())
        cat_probs = list(CATEGORY_DIST_BY_BAND[band].values())

        # stress window (cluster negative tickets) for at_risk / recovering
        stress_center = None
        if drop_week.get(aid) is not None:
            stress_center = drop_week[aid]

        for _ in range(n_tickets):
            tk += 1
            # date: mostly uniform, but oversample stress window
            if stress_center is not None and rng.random() < 0.45:
                d = stress_center + timedelta(days=int(rng.integers(-14, 70)))
                created = min(max(d, start), end)
            else:
                span = max(1, (end - start).days)
                created = start + timedelta(days=int(rng.integers(0, span)))

            tone = pick_p(rng, tone_names, tone_probs)
            category = pick_p(rng, cat_names, cat_probs)
            # force some escalations into stress window
            if stress_center is not None and abs((created - stress_center).days) < 45 and rng.random() < 0.35:
                category = "Escalation"
                tone = "urgent" if rng.random() < 0.6 else "frustrated"
            # tone must match the severity of escalations / outages
            if category == "Escalation" and tone in ("positive", "neutral"):
                tone = "urgent" if rng.random() < 0.55 else "frustrated"
            elif category == "Performance / Outage" and tone == "positive":
                tone = "urgent" if rng.random() < 0.5 else "neutral"

            product = pick(rng, products)
            feature = pick(rng, C.ADVANCED_FEATURES[product])
            priority = pick(rng, PRIORITY_BY_CATEGORY[category])

            subj = pick(rng, T.TICKET_SUBJECTS[category]).format(product=product, feature=feature, industry=industry)
            body = " ".join([
                pick(rng, T.TICKET_BODY_OPENERS[tone]),
                pick(rng, T.TICKET_BODY_CORE[category]),
                pick(rng, T.TICKET_BODY_CLOSERS[tone]),
            ]).format(product=product, feature=feature, industry=industry, csm=csm, company=company)

            mu, sd = TONE_SENTIMENT[tone]
            sentiment = round(float(np.clip(rng.normal(mu, sd), -1, 1)), 3)

            # status & resolution
            days_since = (C.AS_OF_DATE - created).days
            if days_since < 5 and rng.random() < 0.5:
                status = pick(rng, ["Open", "Pending Customer"])
            else:
                status = pick_p(rng, ["Resolved", "Closed", "Pending Customer"], [0.6, 0.32, 0.08])
            rlo, rhi = RES_HOURS_BY_PRIORITY[priority]
            res_hours = round(float(rng.uniform(rlo, rhi)) * (1.4 if category == "Escalation" else 1.0), 1)
            if status in ("Resolved", "Closed"):
                csat = int(pick(rng, TONE_CSAT[tone]))
            else:
                csat = None
                res_hours = None

            rows.append({
                "ticket_id": f"TCK-{100000 + tk}",
                "account_id": aid,
                "created_date": created.isoformat(),
                "channel": pick(rng, C.TICKET_CHANNELS),
                "category": category,
                "priority": priority,
                "status": status,
                "product": product,
                "subject": subj,
                "body": body,
                "sentiment": sentiment,
                "csat": csat,
                "resolution_hours": res_hours,
            })
    df = pd.DataFrame(rows).sort_values(["account_id", "created_date"]).reset_index(drop=True)
    return df


# =========================================================================== #
# 5. CSM NOTES  (rich multi-section narratives -> RAG corpus)
# =========================================================================== #
def _trend_dir(slope):
    if slope > 0.25:
        return "up"
    if slope < -0.25:
        return "down"
    return "flat"

def _support_load(tickets_acc):
    if len(tickets_acc) == 0:
        return "light"
    esc = (tickets_acc["category"] == "Escalation").sum()
    neg = (tickets_acc["sentiment"] < -0.2).mean()
    if esc >= 2 or neg > 0.35:
        return "heavy"
    if neg > 0.15 or esc >= 1:
        return "normal"
    return "light"

def _recent_event_phrase(events_acc, before_date):
    if events_acc is None or len(events_acc) == 0:
        return None, "none"
    ev = events_acc[events_acc["event_date"] <= before_date.isoformat()]
    if len(ev) == 0:
        return None, "none"
    ev = ev.sort_values("event_date").iloc[-1]
    pol = ev["polarity"]
    return ev["headline"], ("headwind" if pol < 0 else ("tailwind" if pol > 0 else "none"))

def _slope_upto(series, upto_date):
    """Linear slope (per week) of adoption over ~13 weeks ending at upto_date."""
    upto = min(upto_date, C.AS_OF_DATE)
    idx = [i for i, w in enumerate(WEEK_STARTS) if w <= upto and not np.isnan(series[i])]
    if len(idx) < 4:
        return 0.0
    tail = idx[-13:]
    y = series[tail]
    x = np.arange(len(y))
    if np.all(np.isnan(y)):
        return 0.0
    return float(np.polyfit(x, y, 1)[0])

def _build_qbr(rng, a, trend, sponsor_status, support_load, event_phrase, event_pol, expansion):
    band = a["_band"]
    company = a["account_name"]
    product = a["primary_product"]
    feature = pick(rng, C.ADVANCED_FEATURES[product])
    sponsor = a["exec_sponsor_name"]
    industry = a["industry"]

    parts = []
    parts.append(pick(rng, T.NOTE_EXEC_SUMMARY[band]).format(company=company, product=product))
    parts.append(pick(rng, T.NOTE_ADOPTION[trend]).format(product=product, feature=feature))
    parts.append(pick(rng, T.NOTE_STAKEHOLDER[sponsor_status]).format(sponsor=sponsor))
    parts.append(pick(rng, T.NOTE_SUPPORT[support_load]))
    if event_phrase:
        parts.append(pick(rng, T.NOTE_EXTERNAL[event_pol]).format(event=event_phrase))
    else:
        parts.append(pick(rng, T.NOTE_EXTERNAL["none"]))
    if expansion:
        parts.append(pick(rng, T.NOTE_EXPANSION).format(feature=feature))

    actions = list(rng.choice(T.NOTE_ACTIONS[band], size=min(3, len(T.NOTE_ACTIONS[band])), replace=False))
    actions = [x.format(company=company, product=product, feature=feature, sponsor=sponsor) for x in actions]
    action_block = "Action items: " + " ".join(f"({i+1}) {x}" for i, x in enumerate(actions))
    parts.append(action_block)
    parts.append(T.NOTE_RENEWAL_OUTLOOK[band])
    return "\n\n".join(parts)

def generate_notes(rng, accounts, usage_series, tickets, events, drop_week):
    rows = []
    nk = 0
    tickets_by_acc = dict(tuple(tickets.groupby("account_id"))) if len(tickets) else {}
    events_by_acc = dict(tuple(events.groupby("account_id"))) if len(events) else {}

    for _, a in accounts.iterrows():
        aid = a["account_id"]
        band = a["_band"]
        company = a["account_name"]
        csm = a["csm_name"]
        sponsor = a["exec_sponsor_name"]
        product = a["primary_product"]
        industry = a["industry"]
        series = usage_series[aid]
        t_acc = tickets_by_acc.get(aid)
        e_acc = events_by_acc.get(aid)
        support_load = _support_load(t_acc) if t_acc is not None else "light"

        start, end = _active_range(a)
        renewal = date.fromisoformat(a["renewal_date"])
        fa = date.fromisoformat(a["forecast_as_of_date"])

        def emit(note_date, note_type, body, sent):
            nonlocal nk
            nk += 1
            rows.append({
                "note_id": f"NOTE-{200000 + nk}",
                "account_id": aid,
                "note_date": note_date.isoformat(),
                "note_type": note_type,
                "author": csm,
                "sentiment": round(sent, 3),
                "body": body,
            })

        # sentiment proxy by band for notes
        band_sent = {"thriving": 0.6, "steady": 0.35, "slipping": -0.2,
                     "at_risk": -0.55, "stalled": -0.35, "recovering": 0.1}[band]

        # 5a. Onboarding kickoff (near active start, if within window)
        cs = date.fromisoformat(a["contract_start_date"])
        if cs >= WINDOW_START:
            body = pick(rng, T.NOTE_ONBOARDING).format(company=company, sponsor=sponsor,
                                                       product=product, industry=industry)
            emit(min(cs + timedelta(days=7), end), "Onboarding Kickoff", body, 0.2)

        # 5b. Quarterly QBRs (~ every 13 weeks)
        d = start + timedelta(days=30)
        while d <= end:
            slope = _slope_upto(series, d)
            trend = _trend_dir(slope)
            ev_phrase, ev_pol = _recent_event_phrase(e_acc, d)
            expansion = C.ARCHETYPES[a["health_archetype"]].get("expansion_signal", False)
            body = _build_qbr(rng, a, trend, a["sponsor_status"], support_load, ev_phrase, ev_pol, expansion)
            emit(d, "Quarterly Business Review", body, band_sent + rng.normal(0, 0.05))
            d = d + timedelta(days=int(rng.integers(85, 98)))

        # 5c. Monthly touchpoints (short) between QBRs
        d = start + timedelta(days=int(rng.integers(12, 25)))
        while d <= end:
            if rng.random() < 0.8:
                opener = pick(rng, T.NOTE_TOUCHPOINT_OPENERS[band]).format(company=company)
                slope = _slope_upto(series, d)
                trend = _trend_dir(slope)
                extra = pick(rng, T.NOTE_ADOPTION[trend]).format(product=product,
                             feature=pick(rng, C.ADVANCED_FEATURES[product]))
                body = opener + " " + extra
                emit(d, "Monthly Touchpoint", body, band_sent + rng.normal(0, 0.08))
            d = d + timedelta(days=int(rng.integers(26, 34)))

        # 5d. Escalation / save play (for at_risk & recovering, tied to stress window)
        if band in ("at_risk", "recovering") and drop_week.get(aid) is not None:
            dw = drop_week[aid]
            issue_ev, _ = _recent_event_phrase(e_acc, dw + timedelta(days=20))
            issue = issue_ev or "a sharp drop in usage and rising escalations"
            body = pick(rng, T.NOTE_ESCALATION).format(company=company, sponsor=sponsor,
                                                       event_or_issue=issue)
            emit(min(dw + timedelta(days=int(rng.integers(5, 25))), end),
                 "Escalation / Save Play", body, -0.4)

        # 5e. Renewal prep (~ forecast_as_of, if within window)
        if WINDOW_START <= fa <= end:
            play = T.RENEWAL_PLAYS[band]
            outlook = T.NOTE_RENEWAL_OUTLOOK[band]
            feature = pick(rng, C.ADVANCED_FEATURES[product])
            body = pick(rng, T.NOTE_RENEWAL_PREP).format(company=company, product=product,
                        feature=feature, sponsor=sponsor, outlook_line=outlook, play=play)
            emit(fa, "Renewal Prep", body, band_sent + rng.normal(0, 0.05))

        # 5f. Expansion discussion (for expanding accounts)
        if C.ARCHETYPES[a["health_archetype"]].get("expansion_signal", False):
            feature = pick(rng, C.ADVANCED_FEATURES[product])
            body = ("Expansion discussion with " + company + ". " +
                    pick(rng, T.NOTE_EXPANSION).format(feature=feature) +
                    " Next step: build the proposal and align on commercials with " + sponsor + ".")
            emit(min(end - timedelta(days=int(rng.integers(20, 120))), end),
                 "Expansion Discussion", body, 0.5)

    df = pd.DataFrame(rows).sort_values(["account_id", "note_date"]).reset_index(drop=True)
    return df


# =========================================================================== #
# 6. FEATURES + OUTCOMES  (causal, from observable signals)
# =========================================================================== #
def compute_features(accounts, usage_series, tickets, events):
    tickets_by_acc = dict(tuple(tickets.groupby("account_id"))) if len(tickets) else {}
    events_by_acc = dict(tuple(events.groupby("account_id"))) if len(events) else {}
    feats = []
    for _, a in accounts.iterrows():
        aid = a["account_id"]
        fa = date.fromisoformat(a["forecast_as_of_date"])
        cutoff = min(fa, C.AS_OF_DATE)
        cutoff_iso = cutoff.isoformat()
        series = usage_series[aid]

        # adoption features up to cutoff
        idx = [i for i, w in enumerate(WEEK_STARTS) if w <= cutoff and not np.isnan(series[i])]
        if len(idx) >= 4:
            tail13 = idx[-13:]
            y = series[tail13]
            x = np.arange(len(y))
            slope = float(np.polyfit(x, y, 1)[0])
            level_last_q = float(np.mean(y))
        else:
            slope, level_last_q = 0.0, float(np.nanmean(series)) if not np.all(np.isnan(series)) else 0.0

        # support features (last 26 weeks before cutoff)
        t_acc = tickets_by_acc.get(aid)
        win_start = (cutoff - timedelta(weeks=26)).isoformat()
        if t_acc is not None:
            recent = t_acc[(t_acc["created_date"] >= win_start) & (t_acc["created_date"] <= cutoff_iso)]
            active_weeks = max(1, len(idx))
            esc_rate = (recent["category"] == "Escalation").sum() / active_weeks
            avg_sent = float(recent["sentiment"].mean()) if len(recent) else 0.0
            csat_vals = recent["csat"].dropna()
            avg_csat = float(csat_vals.mean()) if len(csat_vals) else 3.5
        else:
            esc_rate, avg_sent, avg_csat = 0.0, 0.0, 3.5

        # external events (last 26 weeks)
        e_acc = events_by_acc.get(aid)
        if e_acc is not None:
            rec_ev = e_acc[(e_acc["event_date"] >= win_start) & (e_acc["event_date"] <= cutoff_iso)]
            adverse = int((rec_ev["polarity"] < 0).sum())
            favorable = int((rec_ev["polarity"] > 0).sum())
        else:
            adverse, favorable = 0, 0

        feats.append({
            "account_id": aid,
            "adoption_trend_13w": round(slope, 4),
            "adoption_level_last_q": round(level_last_q, 2),
            "advanced_feature_depth": round(float(a["advanced_adoption_target"]) * 100, 1),
            "product_breadth": int(a["num_products"]),
            "support_escalation_rate": round(float(esc_rate), 4),
            "avg_sentiment": round(avg_sent, 3),
            "avg_csat": round(avg_csat, 2),
            "adverse_events_2q": adverse,
            "favorable_events_2q": favorable,
            "sponsor_change": int(a["sponsor_status"] in ("new", "lost")),
            "sponsor_lost": int(a["sponsor_status"] == "lost"),
            "onboarding_incomplete": int(not bool(a["onboarding_completed"])),
            "days_to_renewal": (date.fromisoformat(a["renewal_date"]) - fa).days,
        })
    return pd.DataFrame(feats)

def _zscore(s):
    s = s.astype(float)
    mu, sd = s.mean(), s.std(ddof=0)
    if sd == 0:
        return s * 0.0
    return (s - mu) / sd

def compute_outcomes(rng, accounts, features):
    f = features.copy()
    # z-score continuous features; keep binaries as-is (centered)
    z = {}
    z["adoption_trend_13w"]     = _zscore(f["adoption_trend_13w"])
    z["adoption_level_last_q"]  = _zscore(f["adoption_level_last_q"])
    z["advanced_feature_depth"] = _zscore(f["advanced_feature_depth"])
    z["product_breadth"]        = _zscore(f["product_breadth"])
    z["support_escalation_rate"]= _zscore(f["support_escalation_rate"])
    z["avg_sentiment"]          = _zscore(f["avg_sentiment"])
    z["avg_csat"]               = _zscore(f["avg_csat"])
    z["adverse_events_2q"]      = _zscore(f["adverse_events_2q"])
    z["sponsor_change"]         = f["sponsor_change"] - f["sponsor_change"].mean()
    z["onboarding_incomplete"]  = f["onboarding_incomplete"] - f["onboarding_incomplete"].mean()
    z["days_to_renewal_norm"]   = _zscore(f["days_to_renewal"])

    W = C.OUTCOME_WEIGHTS
    index = np.zeros(len(f))
    contrib = {k: (W[k] * z[k]).values for k in W}  # per-account contribution per driver
    for k in W:
        index = index + contrib[k]
    noise = rng.normal(0, C.OUTCOME_NOISE_SD, len(f))
    index_noised = index + noise

    # churn probability (sigmoid of -index) for regression-style tasks
    churn_prob = 1.0 / (1.0 + np.exp(index_noised))

    # quantile-based outcome assignment to guarantee a realistic class mix,
    # while preserving the causal ordering induced by the index.
    order = np.argsort(index_noised)  # ascending: worst first
    n = len(f)
    labels = np.empty(n, dtype=object)
    q_churn, q_contract, q_renew = 0.18, 0.10, 0.52  # expand = remainder ~0.20
    n_churn = int(round(q_churn * n))
    n_contract = int(round(q_contract * n))
    n_renew = int(round(q_renew * n))
    ranks = np.empty(n, dtype=int)
    ranks[order] = np.arange(n)
    for i in range(n):
        r = ranks[i]
        if r < n_churn:
            labels[i] = "Churned"
        elif r < n_churn + n_contract:
            labels[i] = "Contracted"
        elif r < n_churn + n_contract + n_renew:
            labels[i] = "Renewed"
        else:
            labels[i] = "Expanded"

    # assemble driver attributions (top +/- drivers per account)
    driver_records = []
    contrib_df = pd.DataFrame(contrib)
    contrib_df["account_id"] = f["account_id"].values
    for i, aid in enumerate(f["account_id"].values):
        row = {k: float(contrib[k][i]) for k in W}
        ordered = sorted(row.items(), key=lambda kv: kv[1])
        top_neg = [{"driver": k, "contribution": round(v, 3)} for k, v in ordered[:3] if v < 0]
        top_pos = [{"driver": k, "contribution": round(v, 3)} for k, v in ordered[::-1][:3] if v > 0]
        driver_records.append({
            "account_id": aid,
            "health_index": round(float(index[i]), 3),
            "health_index_noised": round(float(index_noised[i]), 3),
            "churn_probability": round(float(churn_prob[i]), 4),
            "outcome": labels[i],
            "top_negative_drivers": top_neg,
            "top_positive_drivers": top_pos,
        })

    outcomes = pd.DataFrame({
        "account_id": f["account_id"].values,
        "health_index": np.round(index, 3),
        "churn_probability": np.round(churn_prob, 4),
        "outcome": labels,
    })

    # add reasons consistent with outcome
    reasons = []
    arch_by_acc = dict(zip(accounts["account_id"], accounts["health_archetype"]))
    for i, aid in enumerate(f["account_id"].values):
        out = labels[i]
        if out == "Churned":
            reasons.append(pick(rng, C.CHURN_REASONS))
        elif out == "Contracted":
            reasons.append(pick(rng, C.CONTRACTION_REASONS))
        elif out == "Expanded":
            reasons.append(pick(rng, C.EXPANSION_REASONS))
        else:
            reasons.append("")
    outcomes["outcome_reason"] = reasons
    outcomes = outcomes.merge(accounts[["account_id", "renewal_date"]], on="account_id", how="left")
    outcomes["outcome_date"] = outcomes["renewal_date"]
    outcomes = outcomes.drop(columns=["renewal_date"])

    return outcomes, driver_records
