FROM python:3.10-slim
WORKDIR /app
RUN apt-get update && apt-get install -y gcc default-libmysqlclient-dev pkg-config && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY compliance/ ./compliance/
COPY migrations/ ./migrations/
EXPOSE 5000
ENV FLASK_APP=compliance
ENV PYTHONUNBUFFERED=1
CMD ["python", "-c", "from compliance import create_app; import os; app = create_app(); app.run(host='0.0.0.0', port=5000, debug=False)"]
