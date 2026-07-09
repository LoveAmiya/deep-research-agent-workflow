FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 18181

CMD ["python", "-c", "from report_workbench import run_server; run_server(host='0.0.0.0', port=18181)"]
