"""
config.py
=========
Central configuration for the Meridian Account-Health synthetic dataset.

Meridian (fictional) is a B2B "digital experience platform" vendor that sells
modular enterprise software: content management, digital asset management,
analytics, personalization, campaign/marketing, and commerce. Its customer
success and field teams need to forecast which accounts are trending toward
under-adoption / churn versus renewal / expansion.

Everything in this dataset is invented. No real company, person, product, or
customer data is used. The generative process is deterministic given
RANDOM_SEED so the dataset is fully reproducible.
"""

from datetime import date

# --------------------------------------------------------------------------- #
# Reproducibility & time frame
# --------------------------------------------------------------------------- #
RANDOM_SEED = 20260721

# The last date for which we have observed data (a Sunday). All weekly usage is
# aggregated to the Sunday week-start ending on/ before this date.
AS_OF_DATE = date(2026, 6, 28)
WINDOW_WEEKS = 104                      # ~2 years of weekly history
FORECAST_HORIZON_DAYS = 90              # we forecast ~1 quarter before renewal

N_ACCOUNTS = 260

# --------------------------------------------------------------------------- #
# Vendor / product catalogue
# --------------------------------------------------------------------------- #
VENDOR_NAME = "Meridian"

# Each product/module has rough per-seat weekly usage scale parameters. These
# are multiplied by an account's engagement level (0..1) and licensed seats.
PRODUCTS = {
    "Content Management": {
        "code": "CMS",
        "sessions_per_seat": 4.5,
        "feature_events_per_session": 9.0,
        "api_calls_per_seat": 60.0,
        "storage_gb_per_seat": 0.8,
        "attach_weight": 1.00,          # relative likelihood an account owns it
    },
    "Digital Asset Management": {
        "code": "DAM",
        "sessions_per_seat": 3.0,
        "feature_events_per_session": 7.0,
        "api_calls_per_seat": 40.0,
        "storage_gb_per_seat": 6.0,
        "attach_weight": 0.75,
    },
    "Analytics": {
        "code": "ANL",
        "sessions_per_seat": 6.0,
        "feature_events_per_session": 12.0,
        "api_calls_per_seat": 220.0,
        "storage_gb_per_seat": 1.2,
        "attach_weight": 0.70,
    },
    "Personalization": {
        "code": "PZN",
        "sessions_per_seat": 2.5,
        "feature_events_per_session": 6.0,
        "api_calls_per_seat": 180.0,
        "storage_gb_per_seat": 0.5,
        "attach_weight": 0.45,
    },
    "Campaign": {
        "code": "CMP",
        "sessions_per_seat": 3.5,
        "feature_events_per_session": 8.0,
        "api_calls_per_seat": 90.0,
        "storage_gb_per_seat": 0.4,
        "attach_weight": 0.55,
    },
    "Commerce": {
        "code": "COM",
        "sessions_per_seat": 5.0,
        "feature_events_per_session": 11.0,
        "api_calls_per_seat": 300.0,
        "storage_gb_per_seat": 0.9,
        "attach_weight": 0.35,
    },
}
PRODUCT_NAMES = list(PRODUCTS.keys())

# "Advanced" features per product. Depth of advanced-feature adoption is a
# strong health signal (shallow usage churns more).
ADVANCED_FEATURES = {
    "Content Management": ["Headless delivery", "Workflow automation", "Multi-site management",
                           "Content reuse / fragments", "Localization pipeline"],
    "Digital Asset Management": ["Smart tagging (AI)", "Dynamic media rendering", "Rights management",
                                 "Bulk metadata ops", "Brand portal"],
    "Analytics": ["Custom funnels", "Cohort analysis", "Attribution modeling",
                  "Anomaly alerts", "Data warehouse export"],
    "Personalization": ["A/B/n testing", "Audience segmentation", "Real-time decisioning",
                        "ML recommendations", "Journey orchestration"],
    "Campaign": ["Multi-channel journeys", "Triggered sends", "Dynamic content blocks",
                 "Send-time optimization", "Deliverability tooling"],
    "Commerce": ["Headless storefront", "Promotion engine", "Inventory sync",
                 "Subscription billing", "Marketplace connectors"],
}

# --------------------------------------------------------------------------- #
# Industries (with 12-month seasonality multipliers, Jan..Dec) and regions
# --------------------------------------------------------------------------- #
# Seasonality multiplies weekly engagement. 1.0 = neutral.
INDUSTRIES = {
    "Retail & E-commerce":      [0.88, 0.85, 0.95, 1.00, 1.02, 1.00, 0.98, 1.00, 1.05, 1.15, 1.30, 1.25],
    "Financial Services":       [1.05, 1.00, 1.08, 1.02, 0.98, 0.97, 0.95, 0.95, 1.05, 1.02, 1.00, 1.10],
    "Healthcare & Life Sciences":[0.98, 1.00, 1.02, 1.02, 1.00, 0.98, 0.96, 0.96, 1.02, 1.03, 1.02, 0.95],
    "Manufacturing":            [1.00, 1.00, 1.03, 1.02, 1.00, 1.00, 0.90, 0.92, 1.05, 1.05, 1.03, 0.90],
    "Media & Entertainment":    [1.02, 1.00, 1.02, 1.00, 1.02, 1.05, 1.05, 1.03, 1.05, 1.05, 1.08, 1.10],
    "Technology & Software":    [1.00, 1.02, 1.05, 1.02, 1.02, 1.03, 1.00, 1.00, 1.05, 1.05, 1.02, 0.92],
    "Travel & Hospitality":     [0.90, 0.92, 1.00, 1.05, 1.10, 1.15, 1.18, 1.15, 1.02, 0.98, 0.92, 0.95],
    "Public Sector & Education":[0.95, 1.00, 1.05, 1.05, 1.02, 0.85, 0.78, 0.90, 1.10, 1.08, 1.05, 0.92],
    "Telecommunications":       [1.02, 1.00, 1.02, 1.00, 1.00, 1.00, 1.00, 1.00, 1.03, 1.03, 1.05, 1.05],
    "Consumer Goods":           [0.95, 0.95, 1.00, 1.02, 1.05, 1.05, 1.02, 1.02, 1.05, 1.08, 1.15, 1.12],
}
INDUSTRY_NAMES = list(INDUSTRIES.keys())

REGIONS = {
    "NA":    ["United States", "Canada"],
    "EMEA":  ["United Kingdom", "Germany", "France", "Netherlands", "Sweden", "United Arab Emirates"],
    "APAC":  ["Australia", "Japan", "Singapore", "India"],
    "LATAM": ["Brazil", "Mexico"],
}
REGION_WEIGHTS = {"NA": 0.50, "EMEA": 0.28, "APAC": 0.15, "LATAM": 0.07}

# --------------------------------------------------------------------------- #
# Segments: ACV, seat, and product-count ranges
# --------------------------------------------------------------------------- #
SEGMENTS = {
    "Strategic": {
        "weight": 0.18,
        "acv_range": (450_000, 2_400_000),
        "seat_range": (120, 900),
        "product_count_range": (3, 6),
        "term_weights": {12: 0.15, 24: 0.35, 36: 0.50},
    },
    "Enterprise": {
        "weight": 0.42,
        "acv_range": (120_000, 550_000),
        "seat_range": (40, 260),
        "product_count_range": (2, 4),
        "term_weights": {12: 0.30, 24: 0.45, 36: 0.25},
    },
    "Mid-Market": {
        "weight": 0.40,
        "acv_range": (28_000, 140_000),
        "seat_range": (10, 80),
        "product_count_range": (1, 3),
        "term_weights": {12: 0.55, 24: 0.35, 36: 0.10},
    },
}
SEGMENT_NAMES = list(SEGMENTS.keys())

# --------------------------------------------------------------------------- #
# Health archetypes (latent ground truth that shapes trajectories & narrative)
# --------------------------------------------------------------------------- #
# trajectory params are interpreted by generators.usage_trajectory().
ARCHETYPES = {
    "expanding": {
        "weight": 0.16,
        "start_level": 0.42, "end_level": 0.92, "shape": "growth",
        "volatility": 0.06,
        "ticket_rate": 0.7, "escalation_bias": -0.6, "sentiment_bias": +0.7,
        "advanced_adoption": (0.55, 0.9),
        "sponsor_change_p": 0.10, "expansion_signal": True,
    },
    "stable_healthy": {
        "weight": 0.22,
        "start_level": 0.74, "end_level": 0.78, "shape": "flat",
        "volatility": 0.05,
        "ticket_rate": 0.8, "escalation_bias": -0.3, "sentiment_bias": +0.4,
        "advanced_adoption": (0.45, 0.75),
        "sponsor_change_p": 0.12, "expansion_signal": False,
    },
    "slow_decline": {
        "weight": 0.17,
        "start_level": 0.70, "end_level": 0.30, "shape": "decay",
        "volatility": 0.06,
        "ticket_rate": 1.1, "escalation_bias": +0.4, "sentiment_bias": -0.4,
        "advanced_adoption": (0.15, 0.45),
        "sponsor_change_p": 0.35, "expansion_signal": False,
    },
    "sharp_drop": {
        "weight": 0.10,
        "start_level": 0.72, "end_level": 0.24, "shape": "cliff",
        "volatility": 0.06,
        "ticket_rate": 1.4, "escalation_bias": +0.9, "sentiment_bias": -0.7,
        "advanced_adoption": (0.20, 0.55),
        "sponsor_change_p": 0.55, "expansion_signal": False,
    },
    "onboarding_stall": {
        "weight": 0.10,
        "start_level": 0.10, "end_level": 0.24, "shape": "stall",
        "volatility": 0.05,
        "ticket_rate": 1.2, "escalation_bias": +0.3, "sentiment_bias": -0.3,
        "advanced_adoption": (0.02, 0.20),
        "sponsor_change_p": 0.30, "expansion_signal": False,
    },
    "recovered": {
        "weight": 0.11,
        "start_level": 0.66, "end_level": 0.62, "shape": "vshape",
        "volatility": 0.06,
        "ticket_rate": 1.3, "escalation_bias": +0.5, "sentiment_bias": -0.05,
        "advanced_adoption": (0.35, 0.65),
        "sponsor_change_p": 0.40, "expansion_signal": False,
    },
    "seasonal_healthy": {
        "weight": 0.14,
        "start_level": 0.66, "end_level": 0.72, "shape": "flat",
        "volatility": 0.05,
        "ticket_rate": 0.9, "escalation_bias": -0.2, "sentiment_bias": +0.3,
        "advanced_adoption": (0.40, 0.72),
        "sponsor_change_p": 0.15, "expansion_signal": False,
        "seasonal_gain": 1.9,           # amplifies industry seasonality
    },
}
ARCHETYPE_NAMES = list(ARCHETYPES.keys())

# --------------------------------------------------------------------------- #
# Outcome model  (latent renewal_health_index -> outcome distribution)
# --------------------------------------------------------------------------- #
# Observable feature contributions to the health index. Higher index = healthier.
# Each feature is z-scored / scaled inside generators before weighting.
OUTCOME_WEIGHTS = {
    "adoption_trend_13w":      1.35,   # slope of adoption over last quarter (biggest driver)
    "adoption_level_last_q":   1.10,   # absolute adoption in last quarter
    "advanced_feature_depth":  0.85,   # depth of advanced-feature adoption
    "product_breadth":         0.55,   # number of products owned (stickiness)
    "support_escalation_rate": -0.80,  # escalations per active week
    "avg_sentiment":           0.70,   # ticket/note sentiment
    "avg_csat":                0.55,   # closed-ticket CSAT
    "adverse_events_2q":      -0.75,   # negative external events in last 2 quarters
    "sponsor_change":         -0.60,   # exec sponsor change flagged
    "onboarding_incomplete":  -0.90,   # onboarding never completed
    "days_to_renewal_norm":    0.10,   # slight: more runway, slightly better
}
OUTCOME_NOISE_SD = 0.55                # irreducible noise so labels aren't trivial

# Thresholds on the (noised) index map to outcomes. Tuned to give a realistic
# mix roughly: ~18% churn, ~10% contract, ~52% renew, ~20% expand.
OUTCOME_THRESHOLDS = {                 # index cutoffs, low -> high
    "Churned":    -0.75,               # index < -0.75
    "Contracted":  0.10,               # -0.75 <= index < 0.10
    "Renewed":     1.25,               # 0.10  <= index < 1.25
    "Expanded":    None,               # index >= 1.25
}

CHURN_REASONS = [
    "Low product adoption / weak usage",
    "Executive sponsor departed",
    "Budget cut / cost consolidation",
    "Merger or acquisition disruption",
    "Switched to competitor",
    "Consolidating onto another platform",
    "Unmet integration requirements",
    "Poor onboarding / never operationalized",
    "Dissatisfaction with support",
    "Reorganization eliminated the use case",
]

CONTRACTION_REASONS = [
    "Reduced seat count in renewal",
    "Dropped an underused module",
    "Budget pressure led to downgrade",
    "Consolidated to fewer products",
]

EXPANSION_REASONS = [
    "Added a new product module",
    "Expanded seats to additional teams",
    "Upgraded to a higher tier",
    "Multi-year commitment with uplift",
    "Rolled out to a new business unit",
]

# --------------------------------------------------------------------------- #
# Support & notes taxonomy
# --------------------------------------------------------------------------- #
TICKET_CATEGORIES = ["How-to / Usage", "Bug / Defect", "Feature Request",
                     "Integration / API", "Billing / Licensing", "Performance / Outage",
                     "Escalation", "Onboarding / Enablement"]
TICKET_PRIORITIES = ["P1", "P2", "P3", "P4"]
TICKET_CHANNELS = ["Support Portal", "Email", "In-app", "CSM-logged"]
TICKET_STATUSES = ["Resolved", "Closed", "Open", "Pending Customer"]

NOTE_TYPES = ["Onboarding Kickoff", "Monthly Touchpoint", "Quarterly Business Review",
              "Escalation / Save Play", "Renewal Prep", "Expansion Discussion"]

# External event types (synthetic stand-ins for what a live news / market agent
# would surface). polarity: +1 tailwind, -1 headwind, 0 neutral.
EXTERNAL_EVENT_TYPES = {
    "Leadership change (CxO)":        -1,
    "Layoffs / restructuring":        -1,
    "Earnings miss":                  -1,
    "Acquisition (as target)":        -1,
    "Cost-cutting initiative":        -1,
    "Regulatory / compliance issue":  -1,
    "Earnings beat":                  +1,
    "Funding round / capital raise":  +1,
    "Acquisition (as acquirer)":      +1,
    "New product / market launch":    +1,
    "Executive hire (digital/CX)":    +1,
    "Partnership announcement":        0,
    "Office relocation":               0,
}

# --------------------------------------------------------------------------- #
# Name banks (all fictional)
# --------------------------------------------------------------------------- #
COMPANY_PREFIXES = [
    "Aster", "Beacon", "Cedar", "Alder", "Ever", "Fathom", "Granite", "Harbor",
    "Iron", "Juniper", "Keystone", "Lattice", "Marlowe", "Northwind", "Orchard",
    "Pinnacle", "Quill", "Ridge", "Summit", "Tidewater", "Union", "Vantage",
    "Westgate", "Yonder", "Zephyr", "Copper", "Sable", "Halcyon", "Verdant",
    "Cobalt", "Onyx", "Calder", "Anchor", "Bramble", "Ashby", "Corbin",
    "Ember", "Foundry", "Gale", "Hollis",
]
COMPANY_ROOTS = [
    "Retail", "Financial", "Health", "Logistics", "Media", "Systems", "Foods",
    "Apparel", "Motors", "Energy", "Telecom", "Bank", "Airlines", "Hotels",
    "Pharma", "Devices", "Networks", "Studios", "Brands", "Group", "Labs",
    "Digital", "Commerce", "Mutual", "Partners", "Holdings", "Industries",
    "Analytics", "Robotics", "Payments",
]
COMPANY_SUFFIXES = ["Inc.", "Corp.", "Group", "Ltd.", "LLC", "Holdings", "Co.",
                    "Global", "International", "Partners", "Worldwide", ""]

FIRST_NAMES = [
    "Aisha", "Marcus", "Priya", "Daniel", "Sofia", "Liam", "Yuki", "Omar",
    "Elena", "Noah", "Fatima", "Diego", "Hannah", "Kenji", "Amara", "Lucas",
    "Nadia", "Ethan", "Ingrid", "Rajesh", "Camila", "Tobias", "Leila", "Mateo",
    "Grace", "Arjun", "Zoe", "Felix", "Nia", "Sven", "Rosa", "Andre",
    "Mei", "Jonas", "Tara", "Emeka", "Clara", "Ravi", "Yara", "Oscar",
    "Bianca", "Hugo", "Sana", "Theo", "Lena", "Kwame", "Vera", "Adrian",
]
LAST_NAMES = [
    "Okafor", "Nguyen", "Patel", "Fischer", "Rossi", "Kim", "Silva", "Haddad",
    "Novak", "Andersson", "Reyes", "Schneider", "Kowalski", "Costa", "Ferrari",
    "Larsen", "Mensah", "Dubois", "Bauer", "Petrov", "Marino", "Sato", "Khan",
    "Weber", "Moreau", "Jensen", "Adeyemi", "Vargas", "Holm", "Iqbal",
    "Bianchi", "Sorensen", "Mbeki", "Laurent", "Fontaine", "Nakamura", "Osei",
    "Romero", "Berg", "Salazar",
]
