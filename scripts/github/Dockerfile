FROM python:3.13-slim

WORKDIR /app

COPY scripts/github/github_sync.py scripts/github/test_github_sync.py ./

ENTRYPOINT ["python", "github_sync.py"]
CMD ["sync"]
