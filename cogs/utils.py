import json
import os

CONFIG_PATH = "data/config.json"
VOTES_PATH = "data/votes.json"

def load_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump({}, f)
    with open(CONFIG_PATH) as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

def load_votes():
    if not os.path.exists(VOTES_PATH):
        with open(VOTES_PATH, "w") as f:
            json.dump({}, f)
    with open(VOTES_PATH) as f:
        return json.load(f)

def save_votes(votes):
    with open(VOTES_PATH, "w") as f:
        json.dump(votes, f, indent=2)
