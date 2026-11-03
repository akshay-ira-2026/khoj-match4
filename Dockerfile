FROM rocm/pytorch:latest
WORKDIR /app
RUN pip install --no-cache-dir "transformers>=4.51" accelerate
COPY app.py /app/app.py
# Optional: bake local weights (no API keys at runtime)
# RUN huggingface-cli download Qwen/Qwen3-4B-Instruct-2507 --local-dir /app/models/qwen3-4b-instruct
RUN mkdir -p /app/input /app/output
ENTRYPOINT ["python3", "/app/app.py"]
