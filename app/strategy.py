"""Next-best-action, timing, recovery scoring, and workload prioritisation.

Like segmentation, this layer is fully deterministic and explainable. Given a
borrower's segment it selects the most appropriate action, the channel/time most
likely to reach them (learned from their own response history), and a transparent
0-100 recovery-probability estimate.

The recovery score is a simple, auditable heuristic — NOT a black-box model — so it
can be explained to an agent, supervisor, or regulator on demand.
"""
from __future__ import annotations

from collections import Counter

from .models import Borrower, Channel, NextBestAction, Segment

# --- Segment -> next-best-action (the core recommendation map) ----------------
_ACTION_BY_SEGMENT: dict[Segment, NextBestAction] = {
    Segment.WILLING_BUT_DELAYED: NextBestAction.SMS_REMINDER,
    Segment.HABITUAL_LATE_PAYER: NextBestAction.SMS_REMINDER,
    Segment.HARDSHIP_CASE: NextBestAction.HARDSHIP_SUPPORT,
    Segment.UNRESPONSIVE: NextBestAction.AGENT_CALL,
    Segment.HIGH_RISK_ESCALATION: NextBestAction.ESCALATION,
    Segment.MANUAL_REVIEW: NextBestAction.MANUAL_REVIEW,
}


def recommend_action(borrower: Borrower, segment: Segment) -> tuple[NextBestAction, list[str]]:
    """Return (action, reasons). Layers a few borrower-specific refinements on the
    base segment->action map."""
    action = _ACTION_BY_SEGMENT.get(segment, NextBestAction.MANUAL_REVIEW)
    reasons = [f"Segment '{segment.value}' maps to recommended action '{action.value}'."]

    # Willing borrowers with a larger balance benefit from a structured plan.
    if segment == Segment.WILLING_BUT_DELAYED and borrower.overdue_amount >= 10_000:
        action = NextBestAction.PAYMENT_PLAN_OFFER
        reasons.append(
            f"Outstanding balance ({borrower.overdue_amount:.0f}) is sizeable; "
            "a payment plan offer is more effective than a simple reminder."
        )
    return action, reasons


def best_channel_and_time(borrower: Borrower) -> tuple[Channel, str, list[str]]:
    """Pick the channel/time the borrower is most likely to respond to, learned from
    their history; fall back to their stated preference."""
    reasons: list[str] = []
    responsive = [c for c in borrower.contact_history if c.responded]

    if responsive:
        channel = Counter(c.channel for c in responsive).most_common(1)[0][0]
        reasons.append(
            f"Channel '{channel.value}' chosen: borrower has responded most often via it."
        )
        avg_hour = round(sum(c.hour for c in responsive) / len(responsive))
        window = f"{avg_hour:02d}:00-{(avg_hour + 2) % 24:02d}:00"
        reasons.append(f"Time window {window} chosen from past responsive contact times.")
    else:
        channel = borrower.preferred_channel
        reasons.append(
            f"No responsive history; defaulting to stated preferred channel "
            f"'{channel.value}'."
        )
        window = "10:00-12:00"
        reasons.append("Defaulting to a standard daytime window (10:00-12:00).")

    return channel, window, reasons


def recovery_probability(borrower: Borrower, segment: Segment) -> tuple[int, list[str]]:
    """Transparent 0-100 estimate of recovery likelihood. Higher = more likely to recover.

    Heuristic, not ML: each adjustment is explainable. Starts at a neutral 60 and is
    nudged by the strongest known signals.
    """
    score = 60
    reasons: list[str] = ["Base score 60."]

    # Promise-keeping is the strongest positive behavioural signal.
    if borrower.promises_made:
        keep_rate = borrower.promises_kept / borrower.promises_made
        delta = round((keep_rate - 0.5) * 40)  # +/-20
        score += delta
        reasons.append(
            f"Promise-kept rate {keep_rate:.0%} -> {delta:+d}."
        )

    # Engagement helps; silence hurts.
    if any(c.responded for c in borrower.contact_history):
        score += 10
        reasons.append("Has responded to contact -> +10.")
    elif borrower.contact_history:
        score -= 15
        reasons.append("Contacted but never responded -> -15.")

    # Deeper delinquency lowers recovery odds.
    if borrower.days_past_due >= 90:
        score -= 25
        reasons.append("Days past due >= 90 -> -25.")
    elif borrower.days_past_due >= 30:
        score -= 10
        reasons.append("Days past due >= 30 -> -10.")

    # Hardship lowers near-term recovery odds (but is handled supportively elsewhere).
    if segment == Segment.HARDSHIP_CASE:
        score -= 10
        reasons.append("Hardship case -> -10 (near-term recovery less likely).")

    score = max(0, min(100, score))
    reasons.append(f"Final score (clamped 0-100): {score}.")
    return score, reasons


def priority_score(recovery_prob: int, overdue_amount: float) -> float:
    """Workload ranking: expected recoverable value = P(recover) * amount.

    Surfaces the highest-value, most-recoverable cases first for agents.
    """
    return round((recovery_prob / 100.0) * overdue_amount, 2)
