FROM python:3.12-slim

WORKDIR /app
COPY . agent/
WORKDIR /app/agent

RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

EXPOSE 8088
CMD ["python", "hosted_app.py"]
