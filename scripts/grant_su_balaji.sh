source .env.testing
uv run python scripts/grant_superuser.py --env testing --email "thummala.gc1978@gmail.com"
source .env.production
uv run python scripts/grant_superuser.py --env testing --email "thummala.gc1978@gmail.com"
