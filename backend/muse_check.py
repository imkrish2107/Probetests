"""Step 1 check: sends 'hello' to Muse Spark, prints reply + tokens."""
from models import reply

if __name__ == "__main__":
    r = reply("hello")
    print("reply:", r["text"])
    print("tokens_in:", r["tokens_in"], "tokens_out:", r["tokens_out"])
    print("cost_usd:", r["cost_usd"])
