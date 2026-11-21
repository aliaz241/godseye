FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# God's Eye data lives in godseye.db next to the code.
# On PaaS hosts, mount a persistent disk/volume at /app or the
# database resets on every redeploy.
CMD ["python", "bot.py"]
