#this is the unique point where a ChatOllama instance is constructed,
#parameters are read from benchmark/config.yaml

from pathlib import Path
import yaml
from langchain_community.chat_models import ChatOllama

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "benchmark" / "config.yaml"

PHASES = {"phase1", "phase2"}

def build_llm(phase: str, model_name: str) -> ChatOllama:
    
    if phase not in PHASES:
        raise ValueError(f"unknown phase '{phase}'")

    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    temperature = cfg.get(f"temperature_{phase}")
    if temperature is None:
        raise KeyError(f"missing 'temperature_{phase}'")

    kwargs = {
        "model": model_name,
        "temperature": temperature,
        "seed": cfg.get("seed", 42),
        "num_predict": cfg.get("num_predict", 512),
        "repeat_penalty": cfg.get("repeat_penalty", 1.0),
    }

    if phase == "phase1":
        kwargs["format"] = "json"

    return ChatOllama(**kwargs)
