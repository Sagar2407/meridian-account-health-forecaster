"""
build_dataset.py
================
Runs the full Meridian Account-Health generation pipeline and writes all
artifacts: structured tables (CSV), an unstructured RAG corpus (JSONL), a golden
evaluation set with ground-truth answers, a validation report, and a sanity plot.

Run from the repo root:
    python3 build_dataset.py
"""

import json
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import config as C
import generators as G

DATA = "data"
RAG = "rag_corpus"
EVAL = "eval"
for d in (DATA, RAG, EVAL):
    os.makedirs(d, exist_ok=True)

DRIVER_FRIENDLY = {
    "adoption_trend_13w": "adoption trend (last quarter)",
    "adoption_level_last_q": "recent adoption level",
    "advanced_feature_depth": "advanced-feature depth",
    "product_breadth": "product breadth",
    "support_escalation_rate": "support escalation rate",
    "avg_sentiment": "support/notes sentiment",
    "avg_csat": "CSAT",
    "adverse_events_2q": "adverse external events",
    "sponsor_change": "executive sponsor change",
    "onboarding_incomplete": "incomplete onboarding",
    "days_to_renewal_norm": "time to renewal",
}


def main():
    rng = G.make_rng()
    print("Generating accounts ...")
    accounts = G.generate_accounts(rng)

    print("Generating weekly usage ...")
    usage, usage_series, drop_week = G.generate_usage(rng, accounts)
    accounts["usage_cliff_date"] = accounts["account_id"].map(
        lambda a: drop_week[a].isoformat() if drop_week.get(a) else "")

    print("Generating external events ...")
    events = G.generate_external_events(rng, accounts, drop_week)

    print("Generating support tickets ...")
    tickets = G.generate_tickets(rng, accounts, drop_week)

    print("Generating CSM notes / QBRs ...")
    notes = G.generate_notes(rng, accounts, usage_series, tickets, events, drop_week)

    print("Computing observable features ...")
    features = G.compute_features(accounts, usage_series, tickets, events)

    print("Computing renewal outcomes (causal + noise) ...")
    outcomes, driver_records = G.compute_outcomes(rng, accounts, features)

    # rename internal band column for clarity
    accounts = accounts.rename(columns={"_band": "health_band"})

    # ----------------------------------------------------------------- write CSVs
    accounts_out = accounts.copy()
    accounts.to_csv(f"{DATA}/accounts.csv", index=False)
    usage.to_csv(f"{DATA}/usage_weekly.csv", index=False)
    tickets.to_csv(f"{DATA}/support_tickets.csv", index=False)
    notes.to_csv(f"{DATA}/csm_notes.csv", index=False)
    events.to_csv(f"{DATA}/external_events.csv", index=False)
    features.to_csv(f"{DATA}/account_features.csv", index=False)
    outcomes.to_csv(f"{DATA}/renewal_outcomes.csv", index=False)

    # ----------------------------------------------------------------- RAG corpus
    acc_meta = accounts.set_index("account_id")
    corpus, notes_jsonl, tickets_jsonl = [], [], []

    for _, n in notes.iterrows():
        m = acc_meta.loc[n["account_id"]]
        header = (f"[{n['note_type']}] {m['account_name']} ({m['segment']}, {m['industry']}) "
                  f"- {n['note_date']} - by {n['author']}")
        text = header + "\n" + n["body"]
        rec = {
            "doc_id": n["note_id"], "account_id": n["account_id"],
            "account_name": m["account_name"], "doc_type": "csm_note",
            "subtype": n["note_type"], "date": n["note_date"],
            "segment": m["segment"], "industry": m["industry"],
            "primary_product": m["primary_product"], "sentiment": n["sentiment"],
            "text": text,
        }
        corpus.append(rec)
        notes_jsonl.append(rec)

    for _, t in tickets.iterrows():
        m = acc_meta.loc[t["account_id"]]
        header = (f"[Support Ticket / {t['category']} / {t['priority']}] {m['account_name']} "
                  f"- {t['created_date']} - {t['status']}")
        text = header + "\nSubject: " + t["subject"] + "\n" + t["body"]
        rec = {
            "doc_id": t["ticket_id"], "account_id": t["account_id"],
            "account_name": m["account_name"], "doc_type": "support_ticket",
            "subtype": t["category"], "date": t["created_date"],
            "segment": m["segment"], "industry": m["industry"],
            "primary_product": m["primary_product"], "sentiment": t["sentiment"],
            "text": text,
        }
        corpus.append(rec)
        tickets_jsonl.append(rec)

    def write_jsonl(path, records):
        with open(path, "w") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")

    write_jsonl(f"{RAG}/corpus.jsonl", corpus)
    write_jsonl(f"{RAG}/notes.jsonl", notes_jsonl)
    write_jsonl(f"{RAG}/tickets.jsonl", tickets_jsonl)

    # ----------------------------------------------------------------- ground truth drivers
    with open(f"{EVAL}/ground_truth_drivers.json", "w") as fh:
        json.dump(driver_records, fh, indent=2)

    # ----------------------------------------------------------------- golden QA
    drivers_by_acc = {d["account_id"]: d for d in driver_records}
    merged = accounts.merge(outcomes, on="account_id").merge(features, on="account_id")

    def friendly_drivers(aid, kind):
        d = drivers_by_acc[aid]
        items = d["top_negative_drivers"] if kind == "neg" else d["top_positive_drivers"]
        return [DRIVER_FRIENDLY.get(x["driver"], x["driver"]) for x in items]

    golden = []

    # Q1: portfolio risk ranking
    risk = merged.sort_values("churn_probability", ascending=False).head(15)
    q1_answer = []
    for _, r in risk.iterrows():
        q1_answer.append({
            "account_id": r["account_id"], "account_name": r["account_name"],
            "segment": r["segment"], "churn_probability": r["churn_probability"],
            "actual_outcome": r["outcome"],
            "top_negative_drivers": friendly_drivers(r["account_id"], "neg"),
        })
    golden.append({
        "id": "Q1_portfolio_risk",
        "question": "As of each account's forecast date, which 15 accounts are at highest renewal risk, "
                    "and what are the main drivers for each?",
        "answer_type": "ranked_list",
        "ground_truth": q1_answer,
    })

    # Q2: cliffs coinciding with adverse events
    cliff_accs = accounts[(accounts["usage_cliff_date"] != "")]
    q2 = []
    for _, r in cliff_accs.iterrows():
        aid = r["account_id"]
        ev = events[(events["account_id"] == aid) & (events["polarity"] < 0)]
        if len(ev):
            cliff = date.fromisoformat(r["usage_cliff_date"])
            near = ev[ev["event_date"].apply(
                lambda x: abs((date.fromisoformat(x) - cliff).days) <= 45)]
            if len(near):
                q2.append({
                    "account_id": aid, "account_name": r["account_name"],
                    "usage_cliff_date": r["usage_cliff_date"],
                    "coinciding_event": near.sort_values("event_date").iloc[0]["headline"],
                    "outcome": outcomes.set_index("account_id").loc[aid, "outcome"],
                })
    golden.append({
        "id": "Q2_cliff_event_coincidence",
        "question": "Which accounts show a sharp usage drop that coincides with an adverse external event, "
                    "and what happened at renewal?",
        "answer_type": "list",
        "ground_truth": q2,
    })

    # Q3: expansion candidates
    exp = merged[merged["outcome"] == "Expanded"].sort_values("churn_probability").head(15)
    golden.append({
        "id": "Q3_expansion_candidates",
        "question": "Which accounts are the strongest expansion candidates, and why?",
        "answer_type": "list",
        "ground_truth": [{
            "account_id": r["account_id"], "account_name": r["account_name"],
            "segment": r["segment"],
            "top_positive_drivers": friendly_drivers(r["account_id"], "pos"),
        } for _, r in exp.iterrows()],
    })

    # Q4: rates by segment and industry
    golden.append({
        "id": "Q4_rates_by_segment",
        "question": "What is the outcome distribution (churn / contract / renew / expand) by segment?",
        "answer_type": "table",
        "ground_truth": (merged.groupby(["segment", "outcome"]).size()
                         .unstack(fill_value=0).to_dict(orient="index")),
    })
    golden.append({
        "id": "Q5_rates_by_industry",
        "question": "What is the outcome distribution by industry?",
        "answer_type": "table",
        "ground_truth": (merged.groupby(["industry", "outcome"]).size()
                         .unstack(fill_value=0).to_dict(orient="index")),
    })

    # Q6..: per-account assessments across bands
    per_acc = []
    for band in accounts["health_band"].unique():
        sample = merged[merged["health_band"] == band].sample(
            min(3, (merged["health_band"] == band).sum()), random_state=int(rng.integers(0, 1e6)))
        for _, r in sample.iterrows():
            aid = r["account_id"]
            neg = friendly_drivers(aid, "neg")
            pos = friendly_drivers(aid, "pos")
            rationale = (f"Predicted outcome: {r['outcome']} "
                         f"(churn probability {r['churn_probability']:.2f}). "
                         + (f"Key risk drivers: {', '.join(neg)}. " if neg else "")
                         + (f"Supporting strengths: {', '.join(pos)}." if pos else ""))
            per_acc.append({
                "id": f"Qacc_{aid}",
                "question": f"Assess the account health of {r['account_name']} ({aid}) as of its forecast "
                            f"date and predict its renewal outcome with reasoning.",
                "answer_type": "assessment",
                "ground_truth": {
                    "account_id": aid, "outcome": r["outcome"],
                    "churn_probability": r["churn_probability"],
                    "top_negative_drivers": neg, "top_positive_drivers": pos,
                    "reference_rationale": rationale,
                },
            })
    golden.extend(per_acc)
    write_jsonl(f"{EVAL}/golden_qa.jsonl", golden)

    # ----------------------------------------------------------------- validation report
    outcome_counts = outcomes["outcome"].value_counts().to_dict()
    n = len(accounts)
    churn_by_arch = (merged.groupby("health_archetype")["churn_probability"]
                     .mean().sort_values(ascending=False).round(3).to_dict())
    # sanity correlation: adoption trend vs churn prob (expect negative)
    corr_trend = float(np.corrcoef(merged["adoption_trend_13w"], merged["churn_probability"])[0, 1])
    corr_sent = float(np.corrcoef(merged["avg_sentiment"], merged["churn_probability"])[0, 1])

    report = []
    report.append("# Meridian Account-Health Dataset - Validation Report\n")
    report.append(f"- Accounts: **{n}**")
    report.append(f"- Weekly usage rows: **{len(usage):,}**")
    report.append(f"- Support tickets: **{len(tickets):,}**")
    report.append(f"- CSM notes / QBRs: **{len(notes):,}**")
    report.append(f"- External events: **{len(events):,}**")
    report.append(f"- RAG corpus documents: **{len(corpus):,}**")
    report.append(f"- Golden eval items: **{len(golden)}**\n")
    report.append("## Outcome distribution")
    for k in ["Churned", "Contracted", "Renewed", "Expanded"]:
        c = outcome_counts.get(k, 0)
        report.append(f"- {k}: {c} ({c/n:.1%})")
    report.append("\n## Sanity checks (causal signal is present & correctly signed)")
    report.append(f"- corr(adoption_trend_13w, churn_probability) = **{corr_trend:.3f}**  (expect negative)")
    report.append(f"- corr(avg_sentiment, churn_probability)     = **{corr_sent:.3f}**  (expect negative)")
    report.append("\n## Mean churn probability by latent archetype (expect sensible ordering)")
    for k, v in churn_by_arch.items():
        report.append(f"- {k}: {v}")
    report.append("\n> The latent `health_archetype` / `health_band` columns are ground truth for analysis "
                  "only and must NOT be used as model features. Outcomes are a function of the observable "
                  "feature columns plus irreducible noise.")
    with open(f"{EVAL}/validation_report.md", "w") as fh:
        fh.write("\n".join(report))

    # ----------------------------------------------------------------- sanity plot
    fig, ax = plt.subplots(figsize=(11, 6))
    shown = set()
    for _, a in accounts.iterrows():
        arch = a["health_archetype"]
        if arch in shown:
            continue
        shown.add(arch)
        s = usage_series[a["account_id"]]
        xs = [w for w, v in zip(G.WEEK_STARTS, s) if not np.isnan(v)]
        ys = [v for v in s if not np.isnan(v)]
        ax.plot(xs, ys, label=f"{arch} ({a['account_id']})", linewidth=1.8)
    ax.set_title("Example weekly adoption trajectories, one per latent health archetype")
    ax.set_xlabel("Week")
    ax.set_ylabel("Adoption score (0-100)")
    ax.legend(fontsize=8, ncol=2)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(f"{EVAL}/sanity_trajectories.png", dpi=110)
    plt.close(fig)

    # ----------------------------------------------------------------- console summary
    print("\n=== SUMMARY ===")
    print(f"accounts={n}  usage_rows={len(usage):,}  tickets={len(tickets):,}  "
          f"notes={len(notes):,}  events={len(events):,}  corpus_docs={len(corpus):,}")
    print("outcome distribution:", {k: outcome_counts.get(k, 0) for k in
          ['Churned', 'Contracted', 'Renewed', 'Expanded']})
    print(f"corr(adoption_trend, churn_prob)={corr_trend:.3f}  corr(sentiment, churn_prob)={corr_sent:.3f}")
    print("mean churn_prob by archetype:", churn_by_arch)
    print("Artifacts written to data/, rag_corpus/, eval/")


if __name__ == "__main__":
    main()
