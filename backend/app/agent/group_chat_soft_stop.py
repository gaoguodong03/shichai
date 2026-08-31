"""Hard group-chat auto-run budget."""
MAX_EXPERT_TURNS_PER_STREAM = 32


def expert_turn_budget_exceeded(turns: int, max_turns: int = MAX_EXPERT_TURNS_PER_STREAM) -> bool:
    """Return whether an expert auto-run turn count exceeds the contract budget."""
    return int(turns or 0) > int(max_turns)
