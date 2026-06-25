def reveal_inferred_rules(response_text: str, objective: str = "") -> list[str]:
    """
    Extract simple inferred reasoning patterns from target response.
    This is a safe fallback to prevent crashes.
    """

    if not response_text:
        return []

    rules = []

    sentences = response_text.split(".")
    
    for s in sentences:
        s = s.strip().lower()

        if "if" in s or "would" in s or "consider" in s:
            rules.append(s[:120])

    return rules[:5]
