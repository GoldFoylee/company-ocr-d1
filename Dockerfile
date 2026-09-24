FROM python:3.11-slim

# OpenCV needs these system libraries even in headless mode. libgomp1 (GNU
# OpenMP) is required by paddlepaddle's compute kernels -- without it,
# `import paddle` fails with "ImportError: libgomp.so.1: cannot open shared
# object file".
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
