FROM backend-runtime
ENV LIFEREEL_SERVICE=model-gateway SERVICE_MODE=distributed
COPY services/model-gateway/app.py /app/app.py
WORKDIR /app
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
