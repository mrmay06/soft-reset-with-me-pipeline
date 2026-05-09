from __future__ import annotations

from utils.strategy import load_strategy


def inject_experiment_slot(prompt: str, config: dict, wildcard_prompt: str) -> str:
    """Append active experiment or wildcard guidance to a research prompt."""
    experiment_label = config.get("experiment_label", "baseline")
    if experiment_label == "experiment":
        experiment_id = config.get("experiment_id", "")
        strategy = load_strategy()
        experiments = strategy.get("experiment_slots", {}).get("this_week", [])
        active_exp = next((e for e in experiments if e.get("id") == experiment_id), None)
        if active_exp and active_exp.get("prompt_injection"):
            print(f"[research] A/B experiment slot active: {experiment_id}")
            return f"{prompt}\n\n[EXPERIMENT SLOT — {experiment_id}]\n{active_exp['prompt_injection']}"

    if experiment_label == "wildcard":
        print("[research] Wildcard slot active")
        return f"{prompt}\n\n{wildcard_prompt}"

    return prompt
