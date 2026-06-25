"""PromptEvo strategy subsystem.

Holds reusable strategy intelligence used by the message generator.
Members:
  - strategy_library.StrategyFamily : dataclass describing one principle-based
    strategy family (no stored prompts — only principles and constraints).
  - strategy_library.StrategyLibrary : registry that matches families to
    (weaknesses, goal_category) and ranks them using memory context.
"""
