FROM python:3.13-slim

WORKDIR /app

COPY scripts/hevy/hevy_sync.py scripts/hevy/test_hevy_sync.py ./

ENTRYPOINT ["python", "hevy_sync.py"]
CMD ["sync"]
