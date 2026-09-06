FROM python:3.13-slim

WORKDIR /app

COPY scripts/garmin/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/garmin/garmin_sync.py scripts/garmin/test_garmin_sync.py ./

ENTRYPOINT ["python", "garmin_sync.py"]
CMD ["sync"]
